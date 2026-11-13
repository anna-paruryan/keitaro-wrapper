from conftest import PREFIX


def shares(fake, sid):
    return [o["share"] for o in fake.streams[sid]["offers"]]


def offer_ids(fake, sid):
    return [o["offer_id"] for o in fake.streams[sid]["offers"]]


def url(cid, sid, suffix=""):
    return f"/api/campaigns/{cid}/streams/{sid}{suffix}"


# ------------------------------------------------------------------ список и карточка
def test_list_filters_by_query_and_prefix(http, fake):
    fake.seed_campaign(f"{PREFIX}one", [(101, 100)])
    fake.seed_campaign("someone_else", [(101, 100)])
    fake.seed_campaign(f"{PREFIX}two", [(102, 100)])

    all_ = http.get("/api/campaigns").json()
    assert [c["name"] for c in all_] == [f"{PREFIX}two", "someone_else", f"{PREFIX}one"]  # новые сверху

    mine = http.get("/api/campaigns", params={"mine": True}).json()
    assert {c["name"] for c in mine} == {f"{PREFIX}one", f"{PREFIX}two"}

    assert [c["name"] for c in http.get("/api/campaigns", params={"q": "TWO"}).json()] == [f"{PREFIX}two"]
    assert [c["id"] for c in http.get("/api/campaigns", params={"q": "2"}).json()] == [2]


def test_created_campaigns_are_marked(http, fake):
    http.post("/api/campaigns", json={"name": "x", "geo": "AU", "offer_id": 101})
    fake.seed_campaign(f"{PREFIX}foreign", [(101, 100)])
    flags = {c["name"]: c["created_here"] for c in http.get("/api/campaigns").json()}
    assert flags == {f"{PREFIX}x": True, f"{PREFIX}foreign": False}


def test_detail_shows_streams_offers_names_and_stats(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 60), (102, 40)])
    fake.stats_offer = {101: {"clicks": 40, "campaign_unique_clicks": 30, "conversions": 4, "revenue": 12.5}}
    fake.stats_stream = {sid: {"clicks": 55, "campaign_unique_clicks": 41, "conversions": 4, "revenue": 12.5}}

    data = http.get(f"/api/campaigns/{cid}").json()
    assert data["campaign"]["name"] == f"{PREFIX}c"
    assert data["stats_error"] is None

    redirect, offers = data["streams"]
    assert redirect["kind"] == "redirect"
    assert redirect["target"] == "https://www.google.com"
    assert redirect["filters"] == ["Countries: accept AU"]

    assert offers["kind"] == "offers"
    assert offers["shares_total"] == 100
    assert offers["stats"]["clicks"] == 55
    first, second = offers["offers"]
    assert (first["offer_id"], first["name"], first["share"]) == (101, "Mixfuw BEAUTY-RO", 60)
    assert first["stats"] == {"clicks": 40, "unique": 30, "conversions": 4, "revenue": 12.5}
    assert second["stats"] == {"clicks": 0, "unique": 0, "conversions": 0, "revenue": 0.0}  # в отчёте нет строки = нули


def test_stats_fall_back_to_clicks_only(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    fake.report_mode = "no_extra_metrics"
    data = http.get(f"/api/campaigns/{cid}").json()
    assert data["stats_error"] is None
    assert data["streams"][1]["offers"][0]["stats"]["clicks"] == 40


def test_broken_report_does_not_break_editor(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    fake.report_mode = "fail"
    resp = http.get(f"/api/campaigns/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert "report is broken" in data["stats_error"]
    assert data["streams"][1]["offers"][0]["share"] == 100


def test_unknown_campaign_is_404(http):
    assert http.get("/api/campaigns/777").status_code == 404


# ------------------------------------------------------------------ добавление
def test_add_offer_rebalances_to_100(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])

    r = http.post(url(cid, sid, "/offers"), json={"offer_id": 102})
    assert r.status_code == 200, r.text
    assert offer_ids(fake, sid) == [101, 102]
    assert shares(fake, sid) == [50, 50]

    r = http.post(url(cid, sid, "/offers"), json={"offer_id": 103})
    assert shares(fake, sid) == [34, 33, 33]
    assert sum(shares(fake, sid)) == 100

    # ответ уже содержит свежее состояние
    offers = r.json()["streams"][1]["offers"]
    assert [o["offer_id"] for o in offers] == [101, 102, 103]
    assert r.json()["streams"][1]["shares_total"] == 100


def test_add_sends_only_offers_in_put(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    http.post(url(cid, sid, "/offers"), json={"offer_id": 102})
    (body,) = fake.bodies("PUT", "streams/")
    assert list(body) == ["offers"]
    assert body["offers"] == [
        {"offer_id": 101, "share": 50, "state": "active"},
        {"offer_id": 102, "share": 50, "state": "active"},
    ]


def test_add_duplicate_is_conflict(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    r = http.post(url(cid, sid, "/offers"), json={"offer_id": 101})
    assert r.status_code == 409
    assert fake.paths("PUT", "streams/") == []


def test_add_unknown_offer_is_404(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    assert http.post(url(cid, sid, "/offers"), json={"offer_id": 5555}).status_code == 404
    assert shares(fake, sid) == [100]


def test_add_keeps_existing_ratio(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 80), (102, 20)])
    http.post(url(cid, sid, "/offers"), json={"offer_id": 103})
    s = shares(fake, sid)
    assert sum(s) == 100
    assert s[0] > s[2] > s[1]


# ------------------------------------------------------------------ удаление
def test_remove_offer_rebalances_remaining(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 34), (102, 33), (103, 33)])
    r = http.delete(url(cid, sid, "/offers/102"))
    assert r.status_code == 200, r.text
    assert offer_ids(fake, sid) == [101, 103]
    assert shares(fake, sid) == [50, 50]  # было поровну, поровну и осталось
    assert [o["share"] for o in r.json()["streams"][1]["offers"]] == shares(fake, sid)


def test_remove_keeps_custom_ratio(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 70), (102, 20), (103, 10)])
    http.delete(url(cid, sid, "/offers/103"))
    assert shares(fake, sid) == [78, 22]


def test_cannot_remove_last_offer(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    r = http.delete(url(cid, sid, "/offers/101"))
    assert r.status_code == 409
    assert offer_ids(fake, sid) == [101]


def test_remove_missing_offer_is_404(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 50), (102, 50)])
    assert http.delete(url(cid, sid, "/offers/103")).status_code == 404


def test_equalize(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 70), (102, 20), (103, 10)])
    r = http.post(url(cid, sid, "/equalize"))
    assert r.status_code == 200
    assert shares(fake, sid) == [34, 33, 33]


# ------------------------------------------------------------------ защита и ошибки
def test_foreign_campaign_cannot_be_edited(http, fake):
    cid, sid = fake.seed_campaign("somebody_elses_campaign", [(101, 50), (102, 50)])
    assert http.post(url(cid, sid, "/offers"), json={"offer_id": 103}).status_code == 403
    assert http.delete(url(cid, sid, "/offers/101")).status_code == 403
    assert http.post(url(cid, sid, "/equalize")).status_code == 403
    assert fake.paths("PUT", "streams/") == []
    # но посмотреть можно
    assert http.get(f"/api/campaigns/{cid}").status_code == 200


def test_redirect_stream_cannot_be_edited(http, fake):
    cid, _ = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    geo_sid = min(s["id"] for s in fake.streams.values() if s["campaign_id"] == cid)
    assert http.post(url(cid, geo_sid, "/offers"), json={"offer_id": 102}).status_code == 409


def test_unknown_stream_is_404(http, fake):
    cid, _ = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    assert http.post(url(cid, 99999, "/offers"), json={"offer_id": 102}).status_code == 404


def test_changes_are_logged(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    http.post(url(cid, sid, "/offers"), json={"offer_id": 102})
    http.delete(url(cid, sid, "/offers/101"))
    log = http.get(f"/api/campaigns/{cid}/changes").json()
    assert [(c["action"], c["offer_id"]) for c in log] == [("remove", 101), ("add", 102)]
    assert log[1]["shares_before"] == [100] and log[1]["shares_after"] == [50, 50]


def test_invalid_body_gives_readable_error(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    r = http.post(url(cid, sid, "/offers"), json={"offer_id": 0})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
