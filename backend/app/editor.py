"""Редактор потоков: черновик живёт в нашей базе, в Keitaro уходит только по Push.

Как это устроено (коротко):

* Fetch читает потоки из Keitaro и кладёт их в нашу базу («блокнот»).
* Add / Remove / Bring Back / Pin меняют только блокнот, Keitaro не трогают.
* Push отправляет в Keitaro итоговый список офферов потока и обновляет «что сейчас в Keitaro».
* Cancel выбрасывает всё, что ещё не отправлено.

У каждой строки-оффера два набора чисел:
  share / removed           - то, что видит пользователь (черновик);
  published_share           - что сейчас реально лежит в Keitaro (None = там этого оффера нет).
Разница между ними и есть «жёлтый» поток.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import Settings
from .keitaro import KeitaroClient
from .models import OfferChange, Stream, StreamOffer
from .services import (
    AppError,
    _is_offers_stream,
    _iso,
    _load_campaign,
    _offer_names,
    _stream_offers,
    resolve_offer,
)
from .shares import distribute

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- состояние строки
def offer_dirty(o: StreamOffer) -> bool:
    """Строка отличается от того, что сейчас в Keitaro?"""
    if o.removed:
        return o.published_share is not None  # убрали, но в Keitaro он ещё есть
    if o.published_share is None:
        return True  # новый, в Keitaro его ещё нет
    return o.share != o.published_share


def offer_status(o: StreamOffer) -> str:
    if o.removed:
        return "removed"
    return "new" if o.published_share is None else "active"


def stream_dirty(s: Stream) -> bool:
    return any(offer_dirty(o) for o in s.offers)


def serialize_stream(s: Stream) -> dict:
    """То, что получает React. Поток без офферов - просто заголовок, offers = []."""
    return {
        "id": s.keitaro_id,
        "campaign_id": s.campaign_keitaro_id,
        "name": s.name,
        "position": s.position,
        "has_offers": s.has_offers,
        "dirty": stream_dirty(s),
        "offers": [
            {
                "offer_id": o.offer_id,
                "name": o.offer_name,
                "share": o.share,
                "pinned": o.pinned,
                "status": offer_status(o),  # active | new | removed
                "dirty": offer_dirty(o),
            }
            for o in s.offers
        ],
    }


def _sorted(streams: list[Stream]) -> list[Stream]:
    return sorted(streams, key=lambda s: (s.position, s.keitaro_id))


# --------------------------------------------------------------------------- расчёт долей
def _rebalance(stream: Stream) -> None:
    """Пересчитывает доли: убранные = 0, закреплённые стоят на месте, остальные делят остаток поровну."""
    live = [o for o in stream.offers if not o.removed]
    for o in stream.offers:
        if o.removed:
            o.share = 0
            o.pinned = False
    if not live:
        return
    try:
        shares = distribute([o.share if o.pinned else None for o in live])
    except ValueError as exc:
        raise AppError(422, str(exc)) from exc
    for o, share in zip(live, shares):
        o.share = share


def _save(db: Session, stream: Stream, rebalance: bool = True) -> dict:
    """Пересчитать, сохранить, вернуть поток. Если пересчитать нельзя, откатываем всё и отдаём ошибку."""
    try:
        if rebalance:
            _rebalance(stream)
        db.commit()
    except AppError:
        db.rollback()
        raise
    return serialize_stream(stream)


# --------------------------------------------------------------------------- чтение
def _get_stream(db: Session, stream_id: int) -> Stream:
    stream = db.scalar(select(Stream).where(Stream.keitaro_id == stream_id))
    if stream is None:
        raise AppError(404, f"Stream {stream_id} is unknown. Fetch its campaign first.")
    return stream


def _get_offers_stream(db: Session, stream_id: int) -> Stream:
    stream = _get_stream(db, stream_id)
    if not stream.has_offers:
        raise AppError(409, "This stream has no offers: it is configured as a redirect, so there is nothing to edit.")
    return stream


def _get_row(stream: Stream, offer_id: int) -> StreamOffer:
    row = next((o for o in stream.offers if o.offer_id == offer_id), None)
    if row is None:
        raise AppError(404, f"Offer {offer_id} is not in this stream.")
    return row


def saved_streams(db: Session, campaign_id: int) -> dict:
    """Что лежит в блокноте (без запроса в Keitaro): чтобы после перезагрузки страницы жёлтые потоки не пропали."""
    streams = db.scalars(select(Stream).where(Stream.campaign_keitaro_id == campaign_id)).all()
    return {"campaign_id": campaign_id, "streams": [serialize_stream(s) for s in _sorted(list(streams))]}


# --------------------------------------------------------------------------- Fetch
def _reconcile(stream: Stream, k_offers: list[dict], names: dict[int, str]) -> None:
    """Сверяет строки блокнота с тем, что сейчас в Keitaro."""
    live = {o["offer_id"]: o for o in k_offers if o["state"] == "active"}
    rows = {o.offer_id: o for o in stream.offers}

    for offer_id, k in live.items():
        row = rows.get(offer_id)
        if row is None:  # оффер добавили прямо в Keitaro
            stream.offers.append(
                StreamOffer(
                    offer_id=offer_id,
                    offer_name=names.get(offer_id) or f"Offer #{offer_id}",
                    share=k["share"],
                    published_share=k["share"],
                )
            )
            continue
        was_clean = not offer_dirty(row)  # проверяем ДО обновления published_share
        row.published_share = k["share"]
        row.draft_added = False
        if was_clean:  # своих правок нет: берём то, что в Keitaro
            row.removed = False
            row.share = k["share"]

    for k in k_offers:  # выключен в Keitaro, а у нас его не было: показываем серым, чтобы можно было вернуть
        if k["state"] != "active" and k["offer_id"] not in rows and k["offer_id"] not in live:
            stream.offers.append(
                StreamOffer(offer_id=k["offer_id"], offer_name=names.get(k["offer_id"]) or f"Offer #{k['offer_id']}", share=0, removed=True)
            )
            rows[k["offer_id"]] = stream.offers[-1]

    for offer_id, row in list(rows.items()):
        if offer_id in live or row.published_share is None:
            continue  # он и так был «не в Keitaro»: архивная или новая строка, оставляем
        # Оффер был в Keitaro, а теперь его там нет: его убрали руками. Показываем как наш Remove, уже опубликованный.
        row.published_share = None
        row.removed = True
        row.share = 0
        row.pinned = False
        row.draft_added = False


def fetch_streams(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int) -> dict:
    campaign = _load_campaign(client, settings, campaign_id, for_edit=True)
    raw_streams = [s for s in client.list_campaign_streams(campaign_id) if isinstance(s, dict) and s.get("id") is not None]

    existing = {s.keitaro_id: s for s in db.scalars(select(Stream).where(Stream.campaign_keitaro_id == campaign_id))}
    known_names = {o.offer_id: o.offer_name for s in existing.values() for o in s.offers}
    need = sorted({o["offer_id"] for raw in raw_streams if _is_offers_stream(raw) for o in _stream_offers(raw)} - known_names.keys())
    names = {**known_names, **(_offer_names(client, settings, need) if need else {})}

    seen: set[int] = set()
    for raw in raw_streams:
        sid = int(raw["id"])
        seen.add(sid)
        stream = existing.get(sid)
        if stream is None:
            stream = Stream(keitaro_id=sid, campaign_keitaro_id=campaign_id)
            db.add(stream)
        stream.name = str(raw.get("name") or f"Stream {sid}")
        stream.position = int(raw.get("position") or 0)
        stream.has_offers = _is_offers_stream(raw)
        if stream.has_offers:
            _reconcile(stream, _stream_offers(raw), names)

    for sid, stream in existing.items():  # поток удалили в Keitaro
        if sid not in seen:
            db.delete(stream)
    db.commit()

    result = saved_streams(db, campaign_id)
    result["campaign"] = {"id": campaign_id, "name": str(campaign.get("name") or "")}
    return result


# --------------------------------------------------------------------------- правки черновика
def add_offer(db: Session, client: KeitaroClient, settings: Settings, stream_id: int, offer_id: int) -> dict:
    stream = _get_offers_stream(db, stream_id)
    row = next((o for o in stream.offers if o.offer_id == offer_id), None)
    if row is not None and not row.removed:
        raise AppError(409, f"Offer {offer_id} is already in this stream.")
    offer = resolve_offer(client, settings, offer_id)
    if row is not None:  # оффер уже был в потоке и убран: просто возвращаем
        row.removed = False
        row.offer_name = offer["name"]
    else:
        stream.offers.append(StreamOffer(offer_id=offer_id, offer_name=offer["name"], share=0, published_share=None, draft_added=True))
    return _save(db, stream)


def remove_offer(db: Session, stream_id: int, offer_id: int) -> dict:
    stream = _get_offers_stream(db, stream_id)
    row = _get_row(stream, offer_id)
    if row.removed:
        raise AppError(409, f"Offer {offer_id} is already removed.")
    if row.draft_added:  # он ещё нигде не опубликован: просто выбрасываем строку
        stream.offers.remove(row)
    else:
        row.removed = True
    return _save(db, stream)


def restore_offer(db: Session, stream_id: int, offer_id: int) -> dict:
    stream = _get_offers_stream(db, stream_id)
    row = _get_row(stream, offer_id)
    if not row.removed:
        raise AppError(409, f"Offer {offer_id} is not removed.")
    row.removed = False
    return _save(db, stream)


def pin_offer(db: Session, stream_id: int, offer_id: int, pinned: bool) -> dict:
    """Закрепляет (или откручивает) долю. Сам Pin ничего не пересчитывает: доли поменяются при следующем Add/Remove."""
    stream = _get_offers_stream(db, stream_id)
    row = _get_row(stream, offer_id)
    if row.removed:
        raise AppError(409, "A removed offer cannot be pinned. Bring it back first.")
    row.pinned = pinned
    return _save(db, stream, rebalance=False)


def cancel_stream(db: Session, stream_id: int) -> dict:
    """Выбрасывает всё, что ещё не отправлено в Keitaro. Закрепления (pin) остаются."""
    stream = _get_offers_stream(db, stream_id)
    for row in list(stream.offers):
        if row.draft_added:  # привязку удаляем (сам оффер в Keitaro остаётся)
            stream.offers.remove(row)
        elif row.published_share is None:  # был в архиве (серый): снова в архив
            row.removed, row.share, row.pinned = True, 0, False
        else:
            row.removed, row.share = False, row.published_share
    return _save(db, stream, rebalance=False)


# --------------------------------------------------------------------------- Push
def push_stream(db: Session, client: KeitaroClient, settings: Settings, stream_id: int) -> dict:
    stream = _get_offers_stream(db, stream_id)
    _load_campaign(client, settings, stream.campaign_keitaro_id, for_edit=True)  # защита чужих кампаний
    if not stream_dirty(stream):
        return serialize_stream(stream)

    live = [o for o in stream.offers if not o.removed]
    if not live:
        raise AppError(409, "A stream needs at least one active offer. Add an offer or bring one back before pushing.")
    if sum(o.share for o in live) != 100:
        raise AppError(409, "The shares do not add up to 100%. Add or remove an offer to recalculate them, then push again.")

    current = next(
        (s for s in client.list_campaign_streams(stream.campaign_keitaro_id) if isinstance(s, dict) and s.get("id") == stream_id),
        None,
    )
    if current is None:
        raise AppError(404, "This stream no longer exists in Keitaro. Fetch the campaign again.")
    in_keitaro = {o["offer_id"] for o in _stream_offers(current) if o["state"] == "active"}
    we_think = {o.offer_id for o in stream.offers if o.published_share is not None}
    if in_keitaro != we_think:
        raise AppError(
            409,
            "The offers of this stream were changed in Keitaro after your last Fetch. "
            "Fetch the campaign again to see the changes, then push.",
        )

    before = [o.published_share for o in stream.offers if o.published_share is not None]
    payload = {**current, "offers": [{"offer_id": o.offer_id, "share": o.share, "state": "active"} for o in live]}
    client.update_stream(stream_id, payload)

    for o in stream.offers:  # теперь Keitaro = черновик
        o.published_share = None if o.removed else o.share
        o.draft_added = False
    db.commit()
    _log_change(db, stream, before, [o.share for o in live])
    return serialize_stream(stream)


def _log_change(db: Session, stream: Stream, before: list[int], after: list[int]) -> None:
    try:
        db.add(
            OfferChange(
                campaign_keitaro_id=stream.campaign_keitaro_id,
                stream_keitaro_id=stream.keitaro_id,
                action="push",
                shares_before=before,
                shares_after=after,
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        log.warning("Could not write the change log: %s", exc)


def list_changes(db: Session, campaign_id: int, limit: int = 20) -> list[dict]:
    try:
        rows = db.scalars(
            select(OfferChange).where(OfferChange.campaign_keitaro_id == campaign_id).order_by(OfferChange.id.desc()).limit(limit)
        ).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    return [
        {
            "action": r.action,
            "stream_id": r.stream_keitaro_id,
            "shares_before": r.shares_before,
            "shares_after": r.shares_after,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]