"""Печатает сырые ответы справочников Keitaro и поля существующих кампаний. Только чтение."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.keitaro import KeitaroClient, KeitaroError  # noqa: E402


def show(title, call):
    try:
        data = call()
        print(f"=== {title}: {type(data).__name__}")
        print(json.dumps(data, ensure_ascii=False)[:1200])
    except KeitaroError as exc:
        print(f"=== {title}: FAIL {exc.message}")


def main() -> None:
    s = get_settings()
    c = KeitaroClient(s.keitaro_url, s.keitaro_api_key, s.keitaro_timeout)
    print(f"prefix in .env: {s.campaign_prefix!r}  domain: {s.keitaro_domain!r}  "
          f"group: {s.keitaro_group_name!r}  source: {s.keitaro_source_name!r}\n")
    show("domains", lambda: c._request("GET", "domains"))
    show("groups type=campaigns", lambda: c._request("GET", "groups", params={"type": "campaigns"}))
    show("groups type=offers", lambda: c._request("GET", "groups", params={"type": "offers"}))
    show("traffic_sources", lambda: c._request("GET", "traffic_sources"))
    fields = ("id", "name", "type", "domain_id", "group_id", "traffic_source_id", "cost_type", "cost_auto")
    show("first 4 campaigns (selected fields)",
         lambda: [{k: x.get(k) for k in fields} for x in c.list_campaigns()[:4]])


if __name__ == "__main__":
    main()