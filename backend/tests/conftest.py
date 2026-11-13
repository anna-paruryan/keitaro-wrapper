"""Общие фикстуры: фейковый Keitaro (httpx.MockTransport) + приложение с SQLite в памяти."""

import json
import re
from typing import Any, Optional

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import api as api_module
from app.config import Settings
from app.db import Base, get_db, make_engine
from app.keitaro import KeitaroClient
from app.main import create_app
from app.services import offers_cache

API_KEY = "secret"
PREFIX = "test_ivanov_"


class FakeKeitaro:
    """Мини-эмулятор Admin API: хранит кампании и потоки в памяти и записывает все вызовы."""

    def __init__(self) -> None:
        self.offers = [
            {"id": 101, "name": "Mixfuw BEAUTY-RO", "state": "active"},
            {"id": 102, "name": "Pilulka SLIM-PL", "state": "active"},
            {"id": 103, "name": "Zenith CARE-BG", "state": "active"},
            {"id": 104, "name": "Old offer", "state": "deleted"},
        ]
        self.domains = [{"id": 1, "name": "in.posdk.xyz"}, {"id": 2, "name": "other.example"}]
        self.groups = [
            {"id": 10, "name": "FORTESTS", "type": "campaigns"},
            {"id": 11, "name": "OTHER", "type": "campaigns"},
            {"id": 12, "name": "FORTESTS", "type": "offers"},
        ]
        self.sources = [{"id": 20, "name": "FORTESTS"}, {"id": 21, "name": "Facebook"}]
        self.stream_filters: Any = [{"name": "country"}, {"name": "ip"}]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self._cid = 0
        self._sid = 99
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_stream_number: Optional[int] = None  # на каком по счёту создании потока вернуть 500
        self._created_streams = 0
        self.report_mode = "ok"  # ok | no_extra_metrics | fail
        self.stats_offer = {101: {"clicks": 40, "campaign_unique_clicks": 30, "conversions": 4, "revenue": 12.5}}
        self.stats_stream: dict[int, dict] = {}

    # ---- helpers
    def paths(self, method: str, prefix: str) -> list[str]:
        return [p for m, p, _ in self.calls if m == method and p.startswith(prefix)]

    def bodies(self, method: str, prefix: str) -> list[Any]:
        return [b for m, p, b in self.calls if m == method and p.startswith(prefix)]

    def seed_campaign(self, name: str, offers: list[tuple[int, int]], with_geo_stream: bool = True) -> tuple[int, int]:
        """Готовая кампания: (campaign_id, offer_stream_id)."""
        self._cid += 1
        cid = self._cid
        self.campaigns[cid] = {"id": cid, "name": name, "alias": f"al{cid}", "state": "active"}
        if with_geo_stream:
            self._sid += 1
            self.streams[self._sid] = {
                "id": self._sid, "campaign_id": cid, "position": 1, "name": "AU → Google", "state": "active",
                "schema": "redirect", "action_type": "http", "action_payload": "https://www.google.com",
                "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}], "offers": [],
            }
        self._sid += 1
        sid = self._sid
        self.streams[sid] = {
            "id": sid, "campaign_id": cid, "position": 2, "name": "Offers", "state": "active", "schema": "landings",
            "filters": [], "offers": [{"offer_id": o, "share": s, "state": "active"} for o, s in offers],
        }
        return cid, sid

    # ---- HTTP
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/admin_api/v1/", 1)[1]
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if request.headers.get("Api-Key") != API_KEY:
            return httpx.Response(401, json={"error": "Unauthorized"})
        method = request.method

        def ok(data: Any, status: int = 200) -> httpx.Response:
            return httpx.Response(status, json=data)

        if path == "offers" and method == "GET":
            return ok(self.offers)
        if (m := re.fullmatch(r"offers/(\d+)", path)) and method == "GET":
            found = next((o for o in self.offers if o["id"] == int(m[1])), None)
            return ok(found) if found else httpx.Response(404, json={"error": "Offer not found"})
        if path == "domains":
            return ok(self.domains)
        if path == "groups":
            return ok(self.groups)
        if path == "traffic_sources":
            return ok(self.sources)
        if path == "stream_filters":
            return ok(self.stream_filters)
        if path == "campaigns" and method == "GET":
            return ok(list(self.campaigns.values()))
        if path == "campaigns" and method == "POST":
            self._cid += 1
            self.campaigns[self._cid] = {**body, "id": self._cid}
            return ok(self.campaigns[self._cid])
        if (m := re.fullmatch(r"campaigns/(\d+)", path)):
            cid = int(m[1])
            if cid not in self.campaigns:
                return httpx.Response(404, json={"error": "Campaign not found"})
            if method == "GET":
                return ok(self.campaigns[cid])
            if method == "DELETE":
                del self.campaigns[cid]
                self.streams = {k: v for k, v in self.streams.items() if v["campaign_id"] != cid}
                return httpx.Response(204)
        if (m := re.fullmatch(r"campaigns/(\d+)/streams", path)) and method == "GET":
            cid = int(m[1])
            return ok([s for s in self.streams.values() if s["campaign_id"] == cid])
        if path == "streams" and method == "POST":
            self._created_streams += 1
            if self.fail_stream_number == self._created_streams:
                return httpx.Response(500, json={"error": "Internal error"})
            self._sid += 1
            self.streams[self._sid] = {**body, "id": self._sid}
            return ok(self.streams[self._sid])
        if (m := re.fullmatch(r"streams/(\d+)", path)) and method == "PUT":
            sid = int(m[1])
            if sid not in self.streams:
                return httpx.Response(404, json={"error": "Stream not found"})
            self.streams[sid].update(body)
            return ok(self.streams[sid])
        if path == "report/build" and method == "POST":
            return self._report(body)
        return httpx.Response(404, json={"error": f"no route {method} {path}"})

    def _report(self, body: dict) -> httpx.Response:
        if self.report_mode == "fail":
            return httpx.Response(500, json={"error": "report is broken"})
        if self.report_mode == "no_extra_metrics" and body["metrics"] != ["clicks"]:
            return httpx.Response(400, json={"error": "Unknown metric"})
        group = body["grouping"][0]
        if group == "offer":
            rows = [{"offer": f"Offer {k}", "offer_id": k, **v} for k, v in self.stats_offer.items()]
        else:
            rows = [{"stream": f"Stream {k}", "stream_id": k, **v} for k, v in self.stats_stream.items()]
        if self.report_mode == "no_extra_metrics":
            rows = [{k: v for k, v in r.items() if k in ("offer", "offer_id", "stream", "stream_id", "clicks")} for r in rows]
        return httpx.Response(200, json={"rows": rows, "total": len(rows)})


@pytest.fixture
def fake() -> FakeKeitaro:
    return FakeKeitaro()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        keitaro_url="https://k.example",
        keitaro_api_key=API_KEY,
        campaign_prefix=PREFIX,
        keitaro_domain="in.posdk.xyz",
        keitaro_group_name="FORTESTS",
        keitaro_source_name="FORTESTS",
    )


@pytest.fixture
def keitaro(fake: FakeKeitaro, settings: Settings) -> KeitaroClient:
    return KeitaroClient(settings.keitaro_url, API_KEY, transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def http(fake, settings, keitaro, session_factory) -> TestClient:
    offers_cache.reset()
    app = create_app()

    def _db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[api_module.get_settings_dep] = lambda: settings
    app.dependency_overrides[api_module.get_client] = lambda: keitaro
    app.dependency_overrides[get_db] = _db
    return TestClient(app)
