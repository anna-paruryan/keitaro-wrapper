"""Проверка доступа к Keitaro. Только чтение, ничего не создаёт и не меняет.

Запуск из корня проекта:

    python scripts/check_keitaro.py

Показывает, что реально отвечает API вашего трекера: офферы, домены, группы, источники,
имя фильтра по стране, форму потока и отчёта. Если на вашей версии что-то называется иначе,
это будет видно сразу (и понятно, какую константу поправить в app/keitaro.py или app/services.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import services  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.keitaro import KeitaroClient, KeitaroError  # noqa: E402

failed = 0


def step(title, fn):
    global failed
    try:
        result = fn()
        print(f"OK    {title}")
        return result
    except KeitaroError as exc:
        failed += 1
        print(f"FAIL  {title}\n      {exc.message}")
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"FAIL  {title}\n      {type(exc).__name__}: {exc}")
    return None


def names(items, limit=8):
    shown = [f"{i.get('id')}:{i.get('name')}" for i in items[:limit] if isinstance(i, dict)]
    return ", ".join(shown) + (" …" if len(items) > limit else "")


def main() -> int:
    settings = get_settings()
    if not settings.keitaro_configured:
        print("Fill in KEITARO_URL and KEITARO_API_KEY in .env")
        return 2
    client = KeitaroClient(settings.keitaro_url, settings.keitaro_api_key, settings.keitaro_timeout)
    print(f"Keitaro: {client.root}\n")

    offers = step("GET /offers", client.list_offers)
    if offers:
        print(f"      offers: {len(offers)}; fields: {sorted(offers[0])}")

    for title, fn in (("GET /domains", client.list_domains), ("GET /groups", client.list_groups), ("GET /traffic_sources", client.list_traffic_sources)):
        items = step(title, fn)
        if items:
            print(f"      {len(items)} items: {names(items)}")

    meta = step("default domain / group / source selection", lambda: services.load_meta(client, settings))
    if meta:
        print(f"      defaults: {meta['defaults']}  (names from .env: group={settings.keitaro_group_name}, source={settings.keitaro_source_name})")

    step("GET /stream_filters", client.list_stream_filters)
    print(f"      country filter: '{services.detect_country_filter(client, settings)}»")

    campaigns = step("GET /campaigns", client.list_campaigns) or []
    mine = [c for c in campaigns if str(c.get("name", "")).startswith(settings.campaign_prefix)] if settings.campaign_prefix else []
    sample = (mine or campaigns or [None])[0]
    if sample:
        cid = int(sample["id"])
        print(f"      campaigns: {len(campaigns)}; using #{cid} '{sample.get('name')}' for the check")
        streams = step(f"GET /campaigns/{cid}/streams", lambda: client.list_campaign_streams(cid))
        if streams:
            s = streams[0]
            print(f"      stream: schema={s.get('schema')} type={s.get('type')} filters={s.get('filters')} offers={s.get('offers')}")
        for grouping in ("stream", "offer"):
            rows = step(f"POST /report/build (grouped by {grouping})", lambda g=grouping: services._report_rows(client, cid, g))
            if rows is not None:
                print(f"      rows: {len(rows)}" + (f"; fields: {sorted(rows[0])}" if rows else ""))
    else:
        print("      no campaigns yet: skipping report checks (create one in the form and run again)")

    print("\nSUMMARY:", "everything responds as expected" if not failed else f"problems: {failed}, see FAIL above")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
