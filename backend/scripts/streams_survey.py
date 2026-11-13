"""Показывает, как в трекере выглядят потоки существующих кампаний. Только чтение."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.keitaro import KeitaroClient, KeitaroError  # noqa: E402


def main() -> None:
    s = get_settings()
    client = KeitaroClient(s.keitaro_url, s.keitaro_api_key, s.keitaro_timeout)
    shapes = {}
    for c in client.list_campaigns()[:20]:
        try:
            streams = client.list_campaign_streams(int(c["id"]))
        except KeitaroError:
            continue
        for st in streams:
            key = (st.get("schema"), st.get("type"), st.get("action_type"), bool(st.get("offers")), bool(st.get("filters")))
            shapes.setdefault(key, (c, st))
    for (schema, kind, action, has_offers, has_filters), (c, st) in shapes.items():
        print(f"schema={schema} type={kind} action_type={action} offers={has_offers} filters={has_filters}  (campaign #{c.get('id')} '{c.get('name')}')")
        print("   ", json.dumps(st, ensure_ascii=False)[:700])


if __name__ == "__main__":
    main()