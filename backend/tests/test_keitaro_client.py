import httpx
import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app.config import Settings
from app.keitaro import KeitaroClient, KeitaroError, normalize_base_url
from app.main import create_app


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://tlgk.host", "https://tlgk.host"),
        ("tlgk.host/admin", "https://tlgk.host"),
        ("https://tlgk.host/admin/", "https://tlgk.host"),
        ("http://tlgk.host/admin_api/v1", "http://tlgk.host"),
        ("  tlgk.host  ", "https://tlgk.host"),
    ],
)
def test_normalize_base_url(raw, expected):
    assert normalize_base_url(raw) == expected


def make(handler):
    return KeitaroClient("https://k.example", "key", transport=httpx.MockTransport(handler))


def test_sends_api_key_and_hits_admin_api_path():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["Api-Key"]
        return httpx.Response(200, json=[])

    make(handler).list_offers()
    assert seen == {"url": "https://k.example/admin_api/v1/offers", "key": "key"}


def test_http_error_becomes_keitaro_error_with_hint():
    client = make(lambda r: httpx.Response(403, json={"error": "Forbidden"}))
    with pytest.raises(KeitaroError) as err:
        client.list_offers()
    assert err.value.status == 403
    assert "Forbidden" in err.value.message and "KEITARO_API_KEY" in err.value.message


def test_html_instead_of_json_is_explained():
    client = make(lambda r: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(KeitaroError, match="did not return JSON"):
        client.list_offers()


def test_network_error_is_wrapped():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(KeitaroError, match="Could not reach Keitaro"):
        make(handler).list_offers()


def test_streams_list_falls_back_to_query_endpoint():
    calls = []

    def handler(request):
        calls.append(request.url.path.split("/v1/")[1] + ("?" + request.url.query.decode() if request.url.query else ""))
        if request.url.path.endswith("/campaigns/5/streams"):
            return httpx.Response(404, json={"error": "nope"})
        return httpx.Response(200, json=[{"id": 1}])

    assert make(handler).list_campaign_streams(5) == [{"id": 1}]
    assert calls == ["campaigns/5/streams", "streams?campaign_id=5"]


def test_not_configured_gives_503_with_instruction():
    app = create_app()
    app.dependency_overrides[api_module.get_settings_dep] = lambda: Settings(_env_file=None)
    resp = TestClient(app).get("/api/offers")
    assert resp.status_code == 503
    assert "KEITARO_API_KEY" in resp.json()["detail"]


def test_keitaro_failure_is_502_with_message(http):
    from app.services import offers_cache

    offers_cache.reset()
    http.app.dependency_overrides[api_module.get_client] = lambda: make(
        lambda request: httpx.Response(500, json={"error": "database is down"})
    )
    resp = http.get("/api/offers")
    assert resp.status_code == 502
    assert "database is down" in resp.json()["detail"]


def test_health_works_without_keitaro():
    app = create_app()
    app.dependency_overrides[api_module.get_settings_dep] = lambda: Settings(_env_file=None)
    assert TestClient(app).get("/api/health").json() == {"ok": True, "keitaro_configured": False}
