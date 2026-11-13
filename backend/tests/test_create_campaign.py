from conftest import PREFIX


def create(http, **over):
    body = {"name": "camp1", "geo": "AU", "offer_id": 101, **over}
    return http.post("/api/campaigns", json=body)


def test_creates_campaign_with_two_streams(http, fake):
    resp = create(http, geo="mx, au")
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # кампания
    (campaign,) = fake.campaigns.values()
    assert campaign["name"] == f"{PREFIX}camp1"
    assert campaign["type"] == "position"
    assert (campaign["cost_type"], campaign["cost_value"], campaign["cost_currency"], campaign["cost_auto"]) == ("CPC", 0, "USD", True)
    assert campaign["domain_id"] == 1  # in.posdk.xyz
    assert campaign["group_id"] == 10  # FORTESTS среди групп кампаний, а не среди групп офферов
    assert campaign["traffic_source_id"] == 20
    assert len(campaign["alias"]) >= 6

    # потоки
    geo_stream, offer_stream = sorted(fake.streams.values(), key=lambda s: s["position"])
    assert geo_stream["campaign_id"] == offer_stream["campaign_id"] == campaign["id"]
    assert geo_stream["position"] == 1
    assert geo_stream["schema"] == "redirect"
    assert geo_stream["action_type"] == "http"
    assert geo_stream["action_payload"] == "https://www.google.com"
    assert geo_stream["filters"] == [{"name": "country", "mode": "accept", "payload": ["MX", "AU"]}]

    assert offer_stream["position"] == 2
    assert offer_stream["filters"] == []
    assert offer_stream["offers"] == [{"offer_id": 101, "share": 100, "state": "active"}]

    # ответ
    assert data["campaign"]["id"] == campaign["id"]
    assert data["campaign"]["tracker_url"] == f"https://in.posdk.xyz/{campaign['alias']}"
    assert data["settings"] == {"domain": "in.posdk.xyz", "group": "FORTESTS", "source": "FORTESTS"}
    assert data["geo"] == ["MX", "AU"]


def test_prefix_is_added_once(http, fake):
    create(http, name=f"{PREFIX}already")
    assert [c["name"] for c in fake.campaigns.values()] == [f"{PREFIX}already"]


def test_history_is_saved_and_listed(http):
    create(http)
    items = http.get("/api/history").json()
    assert len(items) == 1
    assert items[0]["name"] == f"{PREFIX}camp1"
    assert items[0]["geo"] == "AU"
    assert items[0]["offer_id"] == 101
    assert items[0]["created_at"].endswith("+00:00")


def test_explicit_domain_group_source_override_defaults(http, fake):
    create(http, domain_id=2, group_id=11, traffic_source_id=21)
    (campaign,) = fake.campaigns.values()
    assert (campaign["domain_id"], campaign["group_id"], campaign["traffic_source_id"]) == (2, 11, 21)


def test_country_filter_name_is_detected_from_api(http, fake):
    fake.stream_filters = [{"name": "country_code"}, {"name": "ip"}]
    create(http)
    geo_stream = min(fake.streams.values(), key=lambda s: s["position"])
    assert geo_stream["filters"][0]["name"] == "country_code"


def test_country_filter_falls_back_when_filters_endpoint_fails(http, fake):
    fake.stream_filters = None  # эндпоинт отвечает JSON null
    resp = create(http)
    assert resp.status_code == 201
    geo_stream = min(fake.streams.values(), key=lambda s: s["position"])
    assert geo_stream["filters"][0]["name"] == "country"


def test_invalid_geo_is_rejected_before_touching_keitaro(http, fake):
    resp = create(http, geo="AUS")
    assert resp.status_code == 422
    assert "AUS" in resp.json()["detail"]
    assert fake.paths("POST", "campaigns") == []


def test_empty_geo_is_rejected(http):
    assert create(http, geo=", ,").status_code == 422


def test_unknown_offer_is_rejected_and_nothing_is_created(http, fake):
    resp = create(http, offer_id=999999)
    assert resp.status_code == 404
    assert "999999" in resp.json()["detail"]
    assert fake.campaigns == {}


def test_deleted_offers_are_not_suggested(http):
    ids = [o["id"] for o in http.get("/api/offers").json()]
    assert 104 not in ids


def test_stream_failure_rolls_back_campaign(http, fake):
    fake.fail_stream_number = 2  # первый поток создался, второй упал
    resp = create(http)
    assert resp.status_code == 502
    assert "The campaign was deleted" in resp.json()["detail"]
    assert fake.campaigns == {}
    assert fake.streams == {}
    assert http.get("/api/history").json() == []


def test_missing_group_gives_clear_error(http, fake):
    fake.groups = [{"id": 11, "name": "OTHER", "type": "campaigns"}]
    resp = create(http)
    assert resp.status_code == 422
    assert "FORTESTS" in resp.json()["detail"]
    assert fake.campaigns == {}


def test_meta_returns_options_and_defaults(http):
    meta = http.get("/api/meta").json()
    assert meta["prefix"] == PREFIX
    assert meta["defaults"] == {"domain_id": 1, "group_id": 10, "traffic_source_id": 20}
    assert [g["id"] for g in meta["groups"]] == [10, 11]  # группа офферов с тем же названием не попала


def test_offer_search_by_name_and_id(http):
    by_name = http.get("/api/offers", params={"q": "pilulka"}).json()
    assert [o["id"] for o in by_name] == [102]
    by_id = http.get("/api/offers", params={"q": "103"}).json()
    assert by_id[0]["id"] == 103
    assert len(http.get("/api/offers", params={"limit": 2}).json()) == 2
