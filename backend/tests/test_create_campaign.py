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
    assert offer_stream["action_type"]  # Keitaro rejects streams without it (422)
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


def test_unknown_group_falls_back_to_first_with_note(http, fake):
    fake.groups = [{"id": 11, "name": "OTHER", "type": "campaigns"}]
    resp = create(http)
    assert resp.status_code == 201, resp.text
    (campaign,) = fake.campaigns.values()
    assert campaign["group_id"] == 11
    assert "FORTESTS" in resp.json()["notes"]["group"]


def test_tracker_without_domains_groups_sources_still_creates(http, fake):
    """Как в реальном трекере: ни доменов, ни источников, группы нет, всё равно кампания создаётся."""
    fake.domains, fake.groups, fake.sources = [], [], []
    resp = create(http)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    (campaign,) = fake.campaigns.values()
    assert "domain_id" not in campaign and "group_id" not in campaign and "traffic_source_id" not in campaign
    assert data["campaign"]["tracker_url"] is None
    assert data["settings"] == {"domain": None, "group": None, "source": None}
    assert set(data["notes"]) == {"domain", "group", "source"}
    assert len(fake.streams) == 2


def test_explicit_unknown_id_is_an_error(http, fake):
    resp = create(http, group_id=999)
    assert resp.status_code == 422
    assert "999" in resp.json()["detail"]
    assert fake.campaigns == {}


def test_meta_returns_options_and_defaults(http):
    meta = http.get("/api/meta").json()
    assert meta["prefix"] == PREFIX
    assert meta["defaults"] == {"domain_id": 1, "group_id": 10, "traffic_source_id": 20}
    assert meta["notes"] == {}
    assert [g["id"] for g in meta["groups"]] == [10, 11]  # группа офферов с тем же названием не попала


def test_offer_search_by_name_and_id(http):
    by_name = http.get("/api/offers", params={"q": "pilulka"}).json()
    assert [o["id"] for o in by_name] == [102]
    by_id = http.get("/api/offers", params={"q": "103"}).json()
    assert by_id[0]["id"] == 103
    assert len(http.get("/api/offers", params={"limit": 2}).json()) == 2


def test_duplicate_name_gives_a_friendly_409(http, fake):
    ok = http.post("/api/campaigns", json={"name": "ui1", "geo": "AU", "offer_id": 101})
    assert ok.status_code == 201

    again = http.post("/api/campaigns", json={"name": "ui1", "geo": "AU", "offer_id": 101})
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert "test_ivanov_ui1" in detail and "already used" in detail and "Choose a different name" in detail
    assert len(fake.campaigns) == 1  # вторая кампания не создана


def test_name_stays_taken_after_a_failed_creation_was_rolled_back(http, fake):
    fake.fail_stream_number = 2
    assert http.post("/api/campaigns", json={"name": "ui2", "geo": "AU", "offer_id": 101}).status_code == 502
    assert fake.campaigns == {}  # откат удалил кампанию (в настоящем Keitaro она уходит в архив)

    fake.fail_stream_number = None
    retry = http.post("/api/campaigns", json={"name": "ui2", "geo": "AU", "offer_id": 101})
    assert retry.status_code == 409  # имя в архиве всё ещё занято: нужно другое
    assert http.post("/api/campaigns", json={"name": "ui3", "geo": "AU", "offer_id": 101}).status_code == 201


def test_other_keitaro_validation_errors_are_explained(http, fake):
    fake.campaign_errors = {"errors": {"group_id": ["Group is invalid"], "name": ["Name is too long"]}}
    r = http.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 101})
    assert r.status_code == 422
    assert r.json()["detail"] == "Keitaro rejected the campaign: group_id: Group is invalid; name: Name is too long."