"""Бизнес-логика: создание кампании, справочники и поиск офферов. Редактор потоков живёт в editor.py."""

import json
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
from .models import Campaign

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
    group = _pick(groups, None, settings.keitaro_group_name) or (groups[0] if groups else None)
    source = _pick(sources, None, settings.keitaro_source_name)

    # Что именно подставили вместо «идеальных» значений из задания (их может не быть в трекере).
    notes: dict[str, str] = {}
    if not domains:
        notes["domain"] = "Keitaro returned no domains for this API key: the campaign will be created without a domain (no tracker link)."
    elif settings.keitaro_domain and _pick(domains, None, settings.keitaro_domain, substring=True) is None:
        notes["domain"] = f"Domain '{settings.keitaro_domain}' was not found: using '{domain['name']}'."
    if not groups:
        notes["group"] = "Keitaro returned no campaign groups: the campaign will be created without a group."
    elif _pick(groups, None, settings.keitaro_group_name) is None:
        notes["group"] = f"Group '{settings.keitaro_group_name}' was not found: using '{group['name']}'."
    if not sources:
        notes["source"] = "Keitaro returned no traffic sources: the campaign will be created without a source."
    elif source is None:
        notes["source"] = f"Traffic source '{settings.keitaro_source_name}' was not found: the campaign will be created without a source."

    return {
        "prefix": settings.campaign_prefix,
        "google_url": settings.google_redirect_url,
        "domains": domains,
        "groups": groups,
        "sources": sources,
        "notes": notes,
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


def _keitaro_field_errors(exc: KeitaroError) -> dict[str, str]:
    """Keitaro отвечает на неверные данные 422 вида {"name": ["сообщение"]}. Превращаем в {поле: "сообщение"}."""
    data: Any = exc.body
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    for key in ("errors", "error", "message", "detail"):  # иногда ответ обёрнут
        if isinstance(data, dict) and isinstance(data.get(key), dict):
            data = data[key]
    if not isinstance(data, dict):
        return {}
    errors = {}
    for field, messages in data.items():
        errors[str(field)] = "; ".join(str(m) for m in messages) if isinstance(messages, list) else str(messages)
    return errors


def _explain_campaign_rejection(exc: KeitaroError, full_name: str) -> None:
    """Если Keitaro отклонил данные кампании (422), объясняем это человеческим языком вместо сырого JSON."""
    if exc.status != 422:
        return
    errors = _keitaro_field_errors(exc)
    if not errors:
        return
    name_error = errors.get("name", "").lower()
    if "used" in name_error or "exist" in name_error:
        raise AppError(
            409,
            f"The name '{full_name}' is already used in Keitaro (the campaign may be in the archive). Choose a different name.",
        ) from exc
    details = "; ".join(f"{field}: {message}" for field, message in errors.items())
    raise AppError(422, f"Keitaro rejected the campaign: {details}.") from exc


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
    # Явно выбранный в форме ID обязан существовать; если ничего не выбрано, а в трекере пусто,
    # кампания создаётся без домена/группы/источника (так же делают кампании других пользователей).
    if domain_id and domain is None:
        raise AppError(422, f"Domain {domain_id} was not found in Keitaro.")
    if group_id and group is None:
        raise AppError(422, f"Group {group_id} was not found among campaign groups.")
    if traffic_source_id and source is None:
        raise AppError(422, f"Traffic source {traffic_source_id} was not found in Keitaro.")
    explicit = {"domain": domain_id, "group": group_id, "source": traffic_source_id}
    notes = {kind: text for kind, text in meta["notes"].items() if not explicit[kind]}

    country_filter = detect_country_filter(client, settings)
    alias = random_alias()

    campaign_payload = {
        "name": full_name,
        "alias": alias,
        "type": "position",  # ротация потоков «по позиции»
        "state": "active",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,  # галочка «Из параметра cost»
    }
    if domain:
        campaign_payload["domain_id"] = domain["id"]
    if group:
        campaign_payload["group_id"] = group["id"]
    if source:
        campaign_payload["traffic_source_id"] = source["id"]
    try:
        campaign = client.create_campaign(campaign_payload)
    except KeitaroError as exc:
        _explain_campaign_rejection(exc, full_name)
        raise
    if not isinstance(campaign, dict) or campaign.get("id") is None:
        raise KeitaroError("Keitaro created the campaign but did not return its ID.")
    campaign_id = int(campaign["id"])
    alias = str(campaign.get("alias") or alias)

    step = "geo stream"
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
        step = "offer stream"
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
                # Keitaro requires action_type on every stream, even one that shows offers
                "action_type": "http",
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
        raise KeitaroError(f"Could not create the {step}: {exc.message} {tail}", status=exc.status, body=exc.body) from exc

    geo_stream_id = int(geo_stream["id"]) if isinstance(geo_stream, dict) and geo_stream.get("id") is not None else None
    offer_stream_id = int(offer_stream["id"]) if isinstance(offer_stream, dict) and offer_stream.get("id") is not None else None
    tracker_url = _tracker_url(domain["name"] if domain else None, alias)

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
                domain_id=domain["id"] if domain else None,
                group_id=group["id"] if group else None,
                traffic_source_id=source["id"] if source else None,
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
        "settings": {
            "domain": domain["name"] if domain else None,
            "group": group["name"] if group else None,
            "source": source["name"] if source else None,
        },
        "notes": notes,
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

# --------------------------------------------------------------------------- вспомогательное для редактора
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