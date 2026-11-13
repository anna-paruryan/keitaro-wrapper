"""Бизнес-логика: создание кампании и редактор офферов."""

import logging
import re
import secrets
import string
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import Settings
from .keitaro import KeitaroClient, KeitaroError
from .models import Campaign, OfferChange
from .shares import shares_after_add, shares_after_remove, shares_equal

log = logging.getLogger(__name__)


class AppError(Exception):
    """Ошибка, понятная пользователю (неверные данные, не найдено, конфликт)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --------------------------------------------------------------------------- валидация
_GEO_SPLIT = re.compile(r"[\s,;]+")


def parse_geo(raw: str) -> list[str]:
    """`mx, AU;ro` -> ['MX', 'AU', 'RO']."""
    codes: list[str] = []
    for part in _GEO_SPLIT.split(raw.strip()):
        if not part:
            continue
        code = part.upper()
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise AppError(422, f"Invalid geo code '{part}': a two-letter country code is required, e.g. AU or MX.")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise AppError(422, "Specify at least one country, e.g. AU.")
    return codes


def build_campaign_name(raw: str, prefix: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise AppError(422, "Campaign name must not be empty.")
    if prefix and not name.startswith(prefix):
        name = prefix + name
    return name


def random_alias(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --------------------------------------------------------------------------- офферы (кэш и поиск)
def _norm_offer(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    try:
        return {"id": int(raw["id"]), "name": str(raw.get("name") or ""), "state": str(raw.get("state") or "")}
    except (TypeError, ValueError):
        return None


class OffersCache:
    """Список офферов нужен для автокомплита и имён в таблице; в Keitaro отдельного поиска нет."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._by_id: dict[int, dict] = {}
        self._loaded_at = 0.0

    def reset(self) -> None:
        with self._lock:
            self._items, self._by_id, self._loaded_at = [], {}, 0.0

    def get(self, client: KeitaroClient, ttl: int, force: bool = False) -> list[dict]:
        with self._lock:
            fresh = bool(self._items) and (time.monotonic() - self._loaded_at) < ttl
            if force or not fresh:
                items = [o for o in (_norm_offer(r) for r in client.list_offers()) if o and o["state"] != "deleted"]
                self._items = sorted(items, key=lambda o: o["id"], reverse=True)
                self._by_id = {o["id"]: o for o in self._items}
                self._loaded_at = time.monotonic()
            return self._items

    def find(self, offer_id: int) -> Optional[dict]:
        with self._lock:
            return self._by_id.get(offer_id)


offers_cache = OffersCache()


def search_offers(client: KeitaroClient, settings: Settings, q: str, limit: int = 15) -> list[dict]:
    items = offers_cache.get(client, settings.offers_cache_ttl)
    q = q.strip().lower()
    if not q:
        return items[:limit]
    exact = [o for o in items if q.isdigit() and str(o["id"]) == q]
    rest = [o for o in items if o not in exact and (q in o["name"].lower() or (q.isdigit() and q in str(o["id"])))]
    return (exact + rest)[:limit]


def resolve_offer(client: KeitaroClient, settings: Settings, offer_id: int) -> dict:
    """Находит оффер по ID (сначала кэш, потом обновление кэша, потом прямой запрос)."""
    offers_cache.get(client, settings.offers_cache_ttl)
    found = offers_cache.find(offer_id)
    if not found:
        offers_cache.get(client, settings.offers_cache_ttl, force=True)
        found = offers_cache.find(offer_id)
    if not found:
        try:
            found = _norm_offer(client.get_offer(offer_id))
        except KeitaroError as exc:
            if exc.status == 404:
                found = None
            else:
                raise
    if not found:
        raise AppError(404, f"Offer {offer_id} was not found in Keitaro.")
    return found


def _offer_names(client: KeitaroClient, settings: Settings, ids: list[int]) -> dict[int, str]:
    """Имена офферов для таблицы. Если Keitaro не отдал список, вернёт пусто, и в UI будет «Оффер #id»."""
    try:
        offers_cache.get(client, settings.offers_cache_ttl)
        if any(offers_cache.find(i) is None for i in ids):
            offers_cache.get(client, settings.offers_cache_ttl, force=True)
    except KeitaroError as exc:
        log.warning("Could not fetch the offers list: %s", exc.message)
    names = {}
    for i in ids:
        found = offers_cache.find(i)
        if found:
            names[i] = found["name"]
    return names


# --------------------------------------------------------------------------- справочники для новых кампаний
def _pick(options: list[dict], explicit: Optional[int], name: str = "", substring: bool = False) -> Optional[dict]:
    if explicit is not None:
        return next((o for o in options if o["id"] == explicit), None)
    if name:
        needle = name.strip().lower().replace("https://", "").replace("http://", "").strip("/")
        for o in options:
            hay = o["name"].lower().strip("/")
            if (needle in hay) if substring else (hay == needle):
                return o
    return None


def _simple(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("id") is not None:
            out.append({"id": int(it["id"]), "name": str(it.get("name") or it["id"])})
    return out


def load_meta(client: KeitaroClient, settings: Settings) -> dict:
    """Домены, группы и источники из API + что выбрано по умолчанию."""
    domains = _simple(client.list_domains())
    # у групп есть тип (campaigns/offers/landings): нужны только группы кампаний
    groups = _simple([g for g in client.list_groups() if isinstance(g, dict) and g.get("type", "campaigns") == "campaigns"])
    sources = _simple(client.list_traffic_sources())

    domain = _pick(domains, None, settings.keitaro_domain, substring=True) or (domains[0] if domains else None)
    group = _pick(groups, None, settings.keitaro_group_name)
    source = _pick(sources, None, settings.keitaro_source_name)
    return {
        "prefix": settings.campaign_prefix,
        "google_url": settings.google_redirect_url,
        "domains": domains,
        "groups": groups,
        "sources": sources,
        "defaults": {
            "domain_id": domain["id"] if domain else None,
            "group_id": group["id"] if group else None,
            "traffic_source_id": source["id"] if source else None,
        },
    }


def _filter_names(raw: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(raw, dict):
        inner = raw.get("filters", raw)
        if isinstance(inner, dict):
            names |= {str(k) for k in inner}
        raw = inner if isinstance(inner, list) else []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict) and item.get("name"):
                names.add(str(item["name"]))
    return names


def detect_country_filter(client: KeitaroClient, settings: Settings) -> str:
    """Имя фильтра по стране спрашиваем у API (GET /stream_filters), чтобы не гадать по версии трекера."""
    if settings.country_filter_name:
        return settings.country_filter_name
    try:
        names = _filter_names(client.list_stream_filters())
    except KeitaroError as exc:
        log.warning("Could not fetch the stream filters list: %s", exc.message)
        return "country"
    for candidate in ("country", "country_code"):
        if candidate in names:
            return candidate
    for name in sorted(names):
        if "country" in name.lower():
            return name
    return "country"


# --------------------------------------------------------------------------- создание кампании
def _tracker_url(domain_name: Optional[str], alias: str) -> Optional[str]:
    if not domain_name:
        return None
    base = domain_name.strip().rstrip("/")
    if not re.match(r"^https?://", base, re.IGNORECASE):
        base = "https://" + base
    return f"{base}/{alias}"


def create_campaign(
    db: Session,
    client: KeitaroClient,
    settings: Settings,
    *,
    name: str,
    geo: str,
    offer_id: int,
    domain_id: Optional[int] = None,
    group_id: Optional[int] = None,
    traffic_source_id: Optional[int] = None,
) -> dict:
    """Кампания с двумя потоками: [гео -> Google] и [все остальные -> оффер]."""
    full_name = build_campaign_name(name, settings.campaign_prefix)
    geos = parse_geo(geo)
    offer = resolve_offer(client, settings, offer_id)

    meta = load_meta(client, settings)
    domain = _pick(meta["domains"], domain_id) if domain_id else _pick(meta["domains"], meta["defaults"]["domain_id"])
    group = _pick(meta["groups"], group_id) if group_id else _pick(meta["groups"], meta["defaults"]["group_id"])
    source = (
        _pick(meta["sources"], traffic_source_id)
        if traffic_source_id
        else _pick(meta["sources"], meta["defaults"]["traffic_source_id"])
    )
    if domain is None:
        raise AppError(422, "Could not choose a domain: Keitaro has no available domains or the given ID is invalid.")
    if group is None:
        raise AppError(422, f"Group not selected: '{settings.keitaro_group_name}' was not found among campaign groups. Pick a group in the form.")
    if source is None:
        raise AppError(422, f"Traffic source not selected: '{settings.keitaro_source_name}' was not found. Pick a source in the form.")

    country_filter = detect_country_filter(client, settings)
    alias = random_alias()

    campaign = client.create_campaign(
        {
            "name": full_name,
            "alias": alias,
            "type": "position",  # ротация потоков «по позиции»
            "state": "active",
            "cost_type": "CPC",
            "cost_value": 0,
            "cost_currency": "USD",
            "cost_auto": True,  # галочка «Из параметра cost»
            "domain_id": domain["id"],
            "group_id": group["id"],
            "traffic_source_id": source["id"],
        }
    )
    if not isinstance(campaign, dict) or campaign.get("id") is None:
        raise KeitaroError("Keitaro created the campaign but did not return its ID.")
    campaign_id = int(campaign["id"])
    alias = str(campaign.get("alias") or alias)

    try:
        geo_stream = client.create_stream(
            {
                "campaign_id": campaign_id,
                "type": "regular",
                "name": f"{', '.join(geos)} → Google",
                "position": 1,
                "weight": 100,
                "state": "active",
                "collect_clicks": True,
                "filter_or": False,
                "schema": "redirect",
                "action_type": "http",
                "action_payload": settings.google_redirect_url,
                "filters": [{"name": country_filter, "mode": "accept", "payload": geos}],
                "landings": [],
                "offers": [],
            }
        )
        offer_stream = client.create_stream(
            {
                "campaign_id": campaign_id,
                "type": "regular",
                "name": f"Offer {offer['id']}",
                "position": 2,
                "weight": 100,
                "state": "active",
                "collect_clicks": True,
                "filter_or": False,
                "schema": "landings",
                "filters": [],
                "landings": [],
                "offers": [{"offer_id": offer["id"], "share": 100, "state": "active"}],
            }
        )
    except KeitaroError as exc:
        # не оставляем в трекере недоделанную кампанию
        cleaned = True
        try:
            client.delete_campaign(campaign_id)
        except KeitaroError as cleanup_exc:
            cleaned = False
            log.warning("Could not roll back campaign %s: %s", campaign_id, cleanup_exc.message)
        tail = "The campaign was deleted." if cleaned else f"Warning: could not delete the unfinished campaign {campaign_id}; delete it manually."
        raise KeitaroError(f"Could not create streams: {exc.message} {tail}", status=exc.status, body=exc.body) from exc

    geo_stream_id = int(geo_stream["id"]) if isinstance(geo_stream, dict) and geo_stream.get("id") is not None else None
    offer_stream_id = int(offer_stream["id"]) if isinstance(offer_stream, dict) and offer_stream.get("id") is not None else None
    tracker_url = _tracker_url(domain["name"], alias)

    warning = None
    try:
        db.add(
            Campaign(
                keitaro_id=campaign_id,
                name=full_name,
                alias=alias,
                geo=",".join(geos),
                offer_id=offer["id"],
                offer_name=offer["name"],
                geo_stream_id=geo_stream_id,
                offer_stream_id=offer_stream_id,
                domain_id=domain["id"],
                group_id=group["id"],
                traffic_source_id=source["id"],
                tracker_url=tracker_url,
            )
        )
        db.commit()
    except SQLAlchemyError as exc:  # кампания в Keitaro уже создана: не роняем запрос из-за истории
        db.rollback()
        log.warning("Could not save the campaign to the local DB: %s", exc)
        warning = "The campaign was created in Keitaro but was not saved to the local history (check migrations: alembic upgrade head)."

    return {
        "campaign": {"id": campaign_id, "name": full_name, "alias": alias, "tracker_url": tracker_url},
        "streams": [
            {"id": geo_stream_id, "position": 1, "title": f"Geo {', '.join(geos)} → {settings.google_redirect_url}"},
            {"id": offer_stream_id, "position": 2, "title": f"Everyone else → offer {offer['id']} {offer['name']}".strip()},
        ],
        "geo": geos,
        "offer": offer,
        "settings": {"domain": domain["name"], "group": group["name"], "source": source["name"]},
        "warning": warning,
    }


def list_history(db: Session, limit: int = 20) -> list[dict]:
    try:
        rows = db.scalars(select(Campaign).order_by(Campaign.id.desc()).limit(limit)).all()
    except SQLAlchemyError as exc:
        db.rollback()
        log.warning("History is unavailable: %s", exc)
        return []
    return [
        {
            "id": r.keitaro_id,
            "name": r.name,
            "alias": r.alias,
            "geo": r.geo,
            "offer_id": r.offer_id,
            "offer_name": r.offer_name,
            "tracker_url": r.tracker_url,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:  # SQLite не хранит часовой пояс; у нас везде UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# --------------------------------------------------------------------------- редактор: список и карточка кампании
def _local_ids(db: Session) -> set[int]:
    try:
        return set(db.scalars(select(Campaign.keitaro_id)).all())
    except SQLAlchemyError:
        db.rollback()
        return set()


def list_campaigns(db: Session, client: KeitaroClient, settings: Settings, q: str = "", mine: bool = False, limit: int = 50) -> list[dict]:
    local = _local_ids(db)
    q = q.strip().lower()
    out = []
    for raw in client.list_campaigns():
        if not isinstance(raw, dict) or raw.get("id") is None:
            continue
        cid = int(raw["id"])
        name = str(raw.get("name") or "")
        if mine and settings.campaign_prefix and not name.startswith(settings.campaign_prefix):
            continue
        if q and not (q in name.lower() or (q.isdigit() and str(cid) == q)):
            continue
        out.append(
            {
                "id": cid,
                "name": name,
                "alias": str(raw.get("alias") or ""),
                "state": str(raw.get("state") or ""),
                "created_here": cid in local,
            }
        )
    out.sort(key=lambda c: c["id"], reverse=True)
    return out[:limit]


_COUNTRY_FILTERS = {"country", "country_code"}
_FILTER_LABELS = {"country": "Countries", "country_code": "Countries"}
_MODE_LABELS = {"accept": "accept", "reject": "exclude"}


def _describe_filter(f: dict) -> str:
    name = str(f.get("name") or "")
    mode = _MODE_LABELS.get(str(f.get("mode") or ""), str(f.get("mode") or ""))
    payload = f.get("payload")
    value = ", ".join(str(p) for p in payload) if isinstance(payload, list) else str(payload or "")
    return f"{_FILTER_LABELS.get(name, name)}: {mode} {value}".strip()


def _stream_offers(stream: dict) -> list[dict]:
    """Офферы потока в нормальном виде: [{offer_id, share, state}]."""
    result = []
    for item in stream.get("offers") or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        raw_id = item.get("offer_id", nested.get("id", item.get("id")))
        try:
            offer_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        try:
            share = int(round(float(item.get("share") or 0)))
        except (TypeError, ValueError):
            share = 0
        result.append({"offer_id": offer_id, "share": share, "state": str(item.get("state") or "active")})
    return result


def _is_offers_stream(stream: dict) -> bool:
    return stream.get("schema") == "landings" or bool(stream.get("offers"))


# --------------------------------------------------------------------------- статистика
STAT_METRICS = ["clicks", "campaign_unique_clicks", "conversions", "revenue"]
_EMPTY_STATS = {"clicks": 0, "unique": 0, "conversions": 0, "revenue": 0.0}


def _num(value: Any, cast=float) -> Any:
    try:
        return cast(value or 0)
    except (TypeError, ValueError):
        return cast(0)


def _row_id(row: dict, key: str) -> Optional[int]:
    for k in (f"{key}_id", key):
        try:
            return int(row[k])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _row_stats(row: dict) -> dict:
    return {
        "clicks": _num(row.get("clicks"), int),
        "unique": _num(row.get("campaign_unique_clicks", row.get("unique_clicks")), int),
        "conversions": _num(row.get("conversions"), int),
        "revenue": _num(row.get("revenue"), float),
    }


def _report_rows(client: KeitaroClient, campaign_id: int, grouping: str) -> list[dict]:
    """Один отчёт «по кампании, сгруппированный по …». Пробуем несколько вариантов запроса: разные версии
    Keitaro по-разному принимают интервал и набор метрик."""
    today = datetime.now(timezone.utc).date().isoformat()
    ranges = [
        {"interval": "all_time", "timezone": "UTC"},
        {"from": "2000-01-01", "to": today, "timezone": "UTC"},
    ]
    metric_sets = [STAT_METRICS, ["clicks"]]
    last_error: Optional[KeitaroError] = None
    for metrics in metric_sets:
        for rng in ranges:
            body = {
                "range": rng,
                "columns": [],
                "metrics": metrics,
                "grouping": [grouping],
                "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
                "summary": False,
                "limit": 1000,
                "offset": 0,
            }
            try:
                data = client.build_report(body)
            except KeitaroError as exc:
                last_error = exc
                if exc.status in (401, 403):
                    raise
                continue
            rows = data.get("rows") if isinstance(data, dict) else data
            return [r for r in (rows or []) if isinstance(r, dict)]
    assert last_error is not None
    raise last_error


def fetch_stats(client: KeitaroClient, campaign_id: int) -> dict:
    """Клики/конверсии по потокам и офферам. Никогда не бросает исключение: если статистика недоступна,
    редактор всё равно работает, а в интерфейсе видно причину."""
    streams: dict[int, dict] = {}
    offers: dict[int, dict] = {}
    try:
        for row in _report_rows(client, campaign_id, "stream"):
            sid = _row_id(row, "stream")
            if sid is not None:
                streams[sid] = _row_stats(row)
        for row in _report_rows(client, campaign_id, "offer"):
            oid = _row_id(row, "offer")
            if oid is not None:
                offers[oid] = _row_stats(row)
    except KeitaroError as exc:
        return {"streams": {}, "offers": {}, "error": exc.message}
    return {"streams": streams, "offers": offers, "error": None}


# --------------------------------------------------------------------------- редактор: карточка и правки
def _load_campaign(client: KeitaroClient, settings: Settings, campaign_id: int, for_edit: bool = False) -> dict:
    try:
        campaign = client.get_campaign(campaign_id)
    except KeitaroError as exc:
        if exc.status == 404:
            raise AppError(404, f"Campaign {campaign_id} was not found.") from exc
        raise
    if not isinstance(campaign, dict):
        raise AppError(404, f"Campaign {campaign_id} was not found.")
    if for_edit and settings.campaign_prefix and not str(campaign.get("name") or "").startswith(settings.campaign_prefix):
        raise AppError(
            403,
            f"Campaign '{campaign.get('name')}' does not start with the prefix {settings.campaign_prefix}. "
            "Other people's campaigns cannot be edited here (CAMPAIGN_PREFIX).",
        )
    return campaign


def get_campaign_detail(client: KeitaroClient, settings: Settings, campaign_id: int, campaign: Optional[dict] = None) -> dict:
    campaign = campaign or _load_campaign(client, settings, campaign_id)
    streams_raw = [s for s in client.list_campaign_streams(campaign_id) if isinstance(s, dict)]
    streams_raw.sort(key=lambda s: (s.get("position") or 0, s.get("id") or 0))

    offer_ids = sorted({o["offer_id"] for s in streams_raw if _is_offers_stream(s) for o in _stream_offers(s)})
    names = _offer_names(client, settings, offer_ids) if offer_ids else {}
    stats = fetch_stats(client, campaign_id)

    streams = []
    for s in streams_raw:
        sid = int(s["id"])
        item: dict = {
            "id": sid,
            "position": s.get("position"),
            "name": str(s.get("name") or f"Stream {sid}"),
            "state": str(s.get("state") or ""),
            "filters": [_describe_filter(f) for f in (s.get("filters") or []) if isinstance(f, dict)],
            "stats": stats["streams"].get(sid, dict(_EMPTY_STATS)),
        }
        if _is_offers_stream(s):
            offers = _stream_offers(s)
            item["kind"] = "offers"
            item["offers"] = [
                {
                    "offer_id": o["offer_id"],
                    "name": names.get(o["offer_id"]) or f"Offer #{o['offer_id']}",
                    "share": o["share"],
                    "state": o["state"],
                    "stats": stats["offers"].get(o["offer_id"], dict(_EMPTY_STATS)),
                }
                for o in offers
            ]
            item["shares_total"] = sum(o["share"] for o in offers)
        else:
            item["kind"] = "redirect"
            item["target"] = str(s.get("action_payload") or "")
            item["action_type"] = str(s.get("action_type") or "")
        streams.append(item)

    return {
        "campaign": {
            "id": campaign_id,
            "name": str(campaign.get("name") or ""),
            "alias": str(campaign.get("alias") or ""),
            "state": str(campaign.get("state") or ""),
        },
        "streams": streams,
        "stats_error": stats["error"],
    }


def _load_offers_stream(client: KeitaroClient, settings: Settings, campaign_id: int, stream_id: int) -> tuple[dict, dict, list[dict]]:
    campaign = _load_campaign(client, settings, campaign_id, for_edit=True)
    stream = next((s for s in client.list_campaign_streams(campaign_id) if isinstance(s, dict) and s.get("id") == stream_id), None)
    if stream is None:
        raise AppError(404, f"Stream {stream_id} was not found in campaign {campaign_id}.")
    if not _is_offers_stream(stream):
        raise AppError(409, "This stream has no offers: it is configured as a redirect, so there is nothing to edit.")
    return campaign, stream, _stream_offers(stream)


def _save_offers(client: KeitaroClient, stream_id: int, offers: list[dict], shares: list[int]) -> None:
    payload = [{"offer_id": o["offer_id"], "share": s, "state": o["state"]} for o, s in zip(offers, shares)]
    client.update_stream(stream_id, {"offers": payload})


def _log_change(db: Session, campaign_id: int, stream_id: int, action: str, offer: Optional[dict], before: list[int], after: list[int]) -> None:
    try:
        db.add(
            OfferChange(
                campaign_keitaro_id=campaign_id,
                stream_keitaro_id=stream_id,
                action=action,
                offer_id=offer["id"] if offer else None,
                offer_name=offer["name"] if offer else None,
                shares_before=before,
                shares_after=after,
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        log.warning("Could not write the change log: %s", exc)


def add_offer(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, stream_id: int, offer_id: int) -> dict:
    campaign, _stream, current = _load_offers_stream(client, settings, campaign_id, stream_id)
    if any(o["offer_id"] == offer_id for o in current):
        raise AppError(409, f"Offer {offer_id} is already in this stream.")
    offer = resolve_offer(client, settings, offer_id)

    before = [o["share"] for o in current]
    after = shares_after_add(before)
    offers = [*current, {"offer_id": offer_id, "share": 0, "state": "active"}]
    _save_offers(client, stream_id, offers, after)
    _log_change(db, campaign_id, stream_id, "add", offer, before, after)
    return get_campaign_detail(client, settings, campaign_id, campaign)


def remove_offer(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, stream_id: int, offer_id: int) -> dict:
    campaign, _stream, current = _load_offers_stream(client, settings, campaign_id, stream_id)
    index = next((i for i, o in enumerate(current) if o["offer_id"] == offer_id), None)
    if index is None:
        raise AppError(404, f"Offer {offer_id} is not in this stream.")
    if len(current) == 1:
        raise AppError(409, "This is the last offer in the stream. Add another one first, then remove this one: a stream without offers sends traffic nowhere.")

    before = [o["share"] for o in current]
    after = shares_after_remove(before, index)
    remaining = [o for i, o in enumerate(current) if i != index]
    _save_offers(client, stream_id, remaining, after)
    removed = offers_cache.find(offer_id) or {"id": offer_id, "name": ""}
    _log_change(db, campaign_id, stream_id, "remove", removed, before, after)
    return get_campaign_detail(client, settings, campaign_id, campaign)


def equalize_shares(db: Session, client: KeitaroClient, settings: Settings, campaign_id: int, stream_id: int) -> dict:
    campaign, _stream, current = _load_offers_stream(client, settings, campaign_id, stream_id)
    before = [o["share"] for o in current]
    after = shares_equal(len(current))
    _save_offers(client, stream_id, current, after)
    _log_change(db, campaign_id, stream_id, "equalize", None, before, after)
    return get_campaign_detail(client, settings, campaign_id, campaign)


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
            "offer_id": r.offer_id,
            "offer_name": r.offer_name,
            "shares_before": r.shares_before,
            "shares_after": r.shares_after,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]
