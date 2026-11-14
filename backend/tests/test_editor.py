"""Редактор потоков: Fetch, черновик (Add/Remove/Bring Back/Pin), Push и Cancel. Сценарии из видео Михаила."""

from conftest import PREFIX


# ------------------------------------------------------------------ помощники
def fetch(http, cid):
    r = http.post(f"/api/campaigns/{cid}/fetch")
    assert r.status_code == 200, r.text
    return r.json()


def offers_stream(data):
    return next(s for s in data["streams"] if s["has_offers"])


def stream_of(http, cid, sid):
    streams = http.get(f"/api/campaigns/{cid}/streams").json()["streams"]
    return next(s for s in streams if s["id"] == sid)


def rows(stream):
    """[(offer_id, share, status)] - коротко для сравнения."""
    return [(o["offer_id"], o["share"], o["status"]) for o in stream["offers"]]


def post(http, path, body=None, status=200):
    r = http.post(f"/api/{path}", json=body)
    assert r.status_code == status, f"{r.status_code}: {r.text}"
    return r.json()


def add(http, sid, offer_id, status=200):
    return post(http, f"streams/{sid}/offers", {"offer_id": offer_id}, status)


def remove(http, sid, offer_id, status=200):
    return post(http, f"streams/{sid}/offers/{offer_id}/remove", None, status)


def restore(http, sid, offer_id, status=200):
    return post(http, f"streams/{sid}/offers/{offer_id}/restore", None, status)


def pin(http, sid, offer_id, pinned=True, status=200):
    return post(http, f"streams/{sid}/offers/{offer_id}/pin", {"pinned": pinned}, status)


def push(http, sid, status=200):
    return post(http, f"streams/{sid}/push", None, status)


def cancel(http, sid):
    return post(http, f"streams/{sid}/cancel")


def keitaro_offers(fake, sid):
    return [(o["offer_id"], o["share"], o["state"]) for o in fake.streams[sid]["offers"]]


def writes(fake):
    return [(m, p) for m, p, _ in fake.calls if m in ("POST", "PUT", "DELETE") and p.startswith("streams")]


def three_offers(fake):
    """Кампания с тремя офферами 34/33/33; в Keitaro есть ещё оффер 105 для добавления."""
    fake.offers.append({"id": 105, "name": "Fourth OFFER", "state": "active"})
    return fake.seed_campaign(f"{PREFIX}c", [(101, 34), (102, 33), (103, 33)])


# ------------------------------------------------------------------ Fetch
def test_fetch_shows_streams_and_a_plain_redirect_stream(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 60), (102, 40)])
    data = fetch(http, cid)

    assert data["campaign"] == {"id": cid, "name": f"{PREFIX}c"}
    redirect, offers = data["streams"]  # по position
    # поток без офферов - просто заголовок: ни фильтров, ни адреса мы не разбираем
    assert redirect == {
        "id": redirect["id"], "campaign_id": cid, "name": "AU → Google", "position": 1,
        "has_offers": False, "dirty": False, "offers": [],
    }
    assert offers["id"] == sid and offers["has_offers"] and not offers["dirty"]
    assert offers["offers"][0] == {
        "offer_id": 101, "name": "Mixfuw BEAUTY-RO", "share": 60, "pinned": False, "status": "active", "dirty": False,
    }
    assert rows(offers) == [(101, 60, "active"), (102, 40, "active")]


def test_fetch_never_writes_to_keitaro(http, fake):
    cid, _ = three_offers(fake)
    fetch(http, cid)
    fetch(http, cid)
    assert [m for m, _, _ in fake.calls if m != "GET"] == []


def test_foreign_campaign_cannot_be_fetched(http, fake):
    cid, _ = fake.seed_campaign("someone_else", [(101, 100)])
    r = http.post(f"/api/campaigns/{cid}/fetch")
    assert r.status_code == 403
    assert "prefix" in r.json()["detail"]


def test_unknown_campaign_is_404(http):
    assert http.post("/api/campaigns/777/fetch").status_code == 404


def test_fetch_is_repeatable_and_does_not_duplicate_rows(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    data = fetch(http, cid)
    assert rows(offers_stream(data)) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]


# ------------------------------------------------------------------ Add / Cancel / Push
def test_add_recalculates_shares_marks_stream_dirty_and_does_not_touch_keitaro(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)

    stream = add(http, sid, 105)
    assert rows(stream) == [(101, 25, "active"), (102, 25, "active"), (103, 25, "active"), (105, 25, "new")]
    assert stream["dirty"] is True
    assert stream["offers"][3]["name"] == "Fourth OFFER"
    assert keitaro_offers(fake, sid) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]  # Keitaro прежний
    assert writes(fake) == []


def test_cancel_drops_unpublished_offers_and_restores_shares(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)

    stream = cancel(http, sid)
    assert rows(stream) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]
    assert stream["dirty"] is False
    assert writes(fake) == []


def test_push_sends_the_whole_stream_with_new_offers(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)

    stream = push(http, sid)
    assert keitaro_offers(fake, sid) == [(101, 25, "active"), (102, 25, "active"), (103, 25, "active"), (105, 25, "active")]
    assert stream["dirty"] is False
    assert rows(stream) == [(101, 25, "active"), (102, 25, "active"), (103, 25, "active"), (105, 25, "active")]

    body = fake.bodies("PUT", f"streams/{sid}")[0]  # уходит весь поток, а не только offers
    assert body["campaign_id"] == cid and body["schema"] == "landings" and body["position"] == 2

    # после Push Cancel уже нечего отменять
    assert rows(cancel(http, sid)) == rows(stream)


def test_push_of_a_clean_stream_does_nothing(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    push(http, sid)
    assert writes(fake) == []


def test_duplicate_unknown_offer_unknown_stream_and_redirect_stream(http, fake):
    cid, sid = three_offers(fake)
    data = fetch(http, cid)
    redirect_id = data["streams"][0]["id"]

    assert "already in this stream" in add(http, sid, 101, status=409)["detail"]
    assert "not found" in add(http, sid, 999, status=404)["detail"]
    assert "Fetch its campaign first" in add(http, 424242, 105, status=404)["detail"]
    assert "redirect" in add(http, redirect_id, 105, status=409)["detail"]
    assert writes(fake) == []


# ------------------------------------------------------------------ Remove / Bring Back
def test_remove_greys_the_row_and_zeroes_its_share(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)

    stream = remove(http, sid, 102)
    assert rows(stream) == [(101, 50, "active"), (102, 0, "removed"), (103, 50, "active")]
    assert stream["dirty"] is True
    assert keitaro_offers(fake, sid)[1] == (102, 33, "active")  # в Keitaro пока на месте


def test_push_after_remove_deletes_the_offer_in_keitaro_but_keeps_it_grey_here(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    remove(http, sid, 102)

    stream = push(http, sid)
    assert keitaro_offers(fake, sid) == [(101, 50, "active"), (103, 50, "active")]
    assert rows(stream) == [(101, 50, "active"), (102, 0, "removed"), (103, 50, "active")]
    assert stream["dirty"] is False


def test_bring_back_returns_the_offer_after_push(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    remove(http, sid, 102)
    push(http, sid)

    stream = restore(http, sid, 102)
    assert rows(stream) == [(101, 34, "active"), (102, 33, "new"), (103, 33, "active")]
    assert stream["dirty"] is True

    push(http, sid)
    assert keitaro_offers(fake, sid) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]


def test_remove_then_bring_back_before_push_leaves_the_stream_clean(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    remove(http, sid, 102)
    stream = restore(http, sid, 102)
    assert rows(stream) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]
    assert stream["dirty"] is False


def test_bring_back_then_cancel_returns_the_offer_to_the_grey_archive(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    remove(http, sid, 102)
    push(http, sid)
    restore(http, sid, 102)

    stream = cancel(http, sid)
    assert rows(stream) == [(101, 50, "active"), (102, 0, "removed"), (103, 50, "active")]
    assert stream["dirty"] is False


def test_cancel_after_remove_brings_the_offer_back(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    remove(http, sid, 102)
    assert rows(cancel(http, sid)) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]


def test_removing_an_unpublished_offer_just_drops_the_row(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)
    stream = remove(http, sid, 105)
    assert rows(stream) == [(101, 34, "active"), (102, 33, "active"), (103, 33, "active")]
    assert stream["dirty"] is False


def test_add_an_offer_that_is_in_the_grey_archive_brings_it_back(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    remove(http, sid, 102)
    push(http, sid)

    stream = add(http, sid, 102)
    assert rows(stream) == [(101, 34, "active"), (102, 33, "new"), (103, 33, "active")]


def test_remove_and_restore_errors(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    assert "not in this stream" in remove(http, sid, 105, status=404)["detail"]
    assert "not removed" in restore(http, sid, 101, status=409)["detail"]
    remove(http, sid, 101)
    assert "already removed" in remove(http, sid, 101, status=409)["detail"]


def test_push_needs_at_least_one_active_offer(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    fetch(http, cid)
    stream = remove(http, sid, 101)
    assert rows(stream) == [(101, 0, "removed")]

    assert "at least one active offer" in push(http, sid, status=409)["detail"]
    assert writes(fake) == []
    assert keitaro_offers(fake, sid) == [(101, 100, "active")]


# ------------------------------------------------------------------ Fetch после правок в Keitaro
def test_offers_removed_in_keitaro_become_grey_removed_on_the_next_fetch(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)

    fake.streams[sid]["offers"] = [o for o in fake.streams[sid]["offers"] if o["offer_id"] != 102]
    stream = offers_stream(fetch(http, cid))
    assert rows(stream) == [(101, 34, "active"), (102, 0, "removed"), (103, 33, "active")]
    assert stream["dirty"] is False  # так в Keitaro и есть: публиковать нечего

    stream = restore(http, sid, 102)  # и Bring Back работает
    assert rows(stream) == [(101, 34, "active"), (102, 33, "new"), (103, 33, "active")]
    push(http, sid)
    assert [o[0] for o in keitaro_offers(fake, sid)] == [101, 102, 103]


def test_offer_disabled_in_keitaro_is_grey_too(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    fake.streams[sid]["offers"][1]["state"] = "disabled"
    assert rows(offers_stream(fetch(http, cid)))[1] == (102, 0, "removed")

    # и если оффер выключен с самого начала, мы о нём не знали: показываем серым
    cid2, sid2 = fake.seed_campaign(f"{PREFIX}d", [(101, 100)])
    fake.streams[sid2]["offers"].append({"offer_id": 103, "share": 0, "state": "disabled"})
    assert rows(offers_stream(fetch(http, cid2))) == [(101, 100, "active"), (103, 0, "removed")]


def test_offers_added_in_keitaro_appear_on_fetch(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 100)])
    fetch(http, cid)
    fake.streams[sid]["offers"] = [
        {"offer_id": 101, "share": 50, "state": "active"},
        {"offer_id": 102, "share": 50, "state": "active"},
    ]
    stream = offers_stream(fetch(http, cid))
    assert rows(stream) == [(101, 50, "active"), (102, 50, "active")]
    assert stream["offers"][1]["name"] == "Pilulka SLIM-PL"


def test_fetch_keeps_unpublished_changes(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)

    stream = offers_stream(fetch(http, cid))
    assert rows(stream) == [(101, 25, "active"), (102, 25, "active"), (103, 25, "active"), (105, 25, "new")]
    assert stream["dirty"] is True


def test_fetch_forgets_streams_deleted_in_keitaro(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    del fake.streams[sid]
    assert [s["id"] for s in fetch(http, cid)["streams"]] == [s["id"] for s in fake.streams.values()]


def test_push_is_refused_if_offers_changed_in_keitaro_after_fetch(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)
    fake.streams[sid]["offers"] = fake.streams[sid]["offers"][:2]  # кто-то убрал оффер 103 прямо в Keitaro

    assert "Fetch the campaign again" in push(http, sid, status=409)["detail"]
    assert writes(fake) == []


# ------------------------------------------------------------------ Pin
def test_pinned_share_stays_while_the_others_are_recalculated(http, fake):
    """Сценарий из видео: 4 оффера по 25%, закрепляем один, убираем и возвращаем другой."""
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)
    push(http, sid)

    stream = pin(http, sid, 101)
    assert stream["offers"][0]["pinned"] is True
    assert stream["dirty"] is False  # сам Pin ничего не пересчитывает

    stream = remove(http, sid, 103)
    assert rows(stream) == [(101, 25, "active"), (102, 38, "active"), (103, 0, "removed"), (105, 37, "active")]
    assert sum(o["share"] for o in stream["offers"]) == 100

    stream = restore(http, sid, 103)  # вернули до Push: всё снова как в Keitaro
    assert rows(stream) == [(101, 25, "active"), (102, 25, "active"), (103, 25, "active"), (105, 25, "active")]
    assert stream["dirty"] is False

    remove(http, sid, 103)
    stream = push(http, sid)
    assert keitaro_offers(fake, sid) == [(101, 25, "active"), (102, 38, "active"), (105, 37, "active")]
    assert stream["offers"][0]["pinned"] is True  # закрепление переживает Push

    stream = restore(http, sid, 103)  # теперь оффер возвращается как новый
    assert rows(stream) == [(101, 25, "active"), (102, 25, "active"), (103, 25, "new"), (105, 25, "active")]


def test_pin_keeps_a_custom_share_when_offers_change(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 60), (102, 40)])
    fake.offers.append({"id": 105, "name": "Fourth OFFER", "state": "active"})
    fetch(http, cid)
    pin(http, sid, 101)

    stream = add(http, sid, 105)
    assert rows(stream) == [(101, 60, "active"), (102, 20, "active"), (105, 20, "new")]


def test_pin_does_not_change_shares_or_dirty_state(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 60), (102, 40)])
    fetch(http, cid)
    stream = pin(http, sid, 101)
    assert rows(stream) == [(101, 60, "active"), (102, 40, "active")]
    assert stream["dirty"] is False
    assert pin(http, sid, 101, pinned=False)["offers"][0]["pinned"] is False


def test_removing_a_pinned_offer_unpins_it(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    pin(http, sid, 101)
    stream = remove(http, sid, 101)
    assert stream["offers"][0]["pinned"] is False
    assert "removed offer cannot be pinned" in pin(http, sid, 101, status=409)["detail"]


def test_pins_that_leave_no_room_are_rejected_and_nothing_changes(http, fake):
    cid, sid = fake.seed_campaign(f"{PREFIX}c", [(101, 50), (102, 50)])
    fetch(http, cid)
    pin(http, sid, 101)
    pin(http, sid, 102)

    r = add(http, sid, 103, status=422)
    assert "no room" in r["detail"]
    assert rows(stream_of(http, cid, sid)) == [(101, 50, "active"), (102, 50, "active")]  # откат: 103 не появился


def test_all_pinned_offers_must_add_up_to_100(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    pin(http, sid, 101)
    pin(http, sid, 102)
    r = remove(http, sid, 103, status=422)  # 34 + 33 != 100
    assert "add up to 100" in r["detail"]
    assert rows(stream_of(http, cid, sid))[2] == (103, 33, "active")


# ------------------------------------------------------------------ блокнот и журнал
def test_drafts_survive_a_page_reload(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)

    saved = http.get(f"/api/campaigns/{cid}/streams").json()
    assert saved["campaign_id"] == cid
    stream = next(s for s in saved["streams"] if s["id"] == sid)
    assert stream["dirty"] is True
    assert rows(stream)[3] == (105, 25, "new")


def test_saved_streams_are_empty_before_the_first_fetch(http):
    assert http.get("/api/campaigns/5/streams").json() == {"campaign_id": 5, "streams": []}


def test_push_is_written_to_the_change_log(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)
    push(http, sid)

    log = http.get(f"/api/campaigns/{cid}/changes").json()
    assert len(log) == 1
    assert log[0]["action"] == "push" and log[0]["stream_id"] == sid
    assert log[0]["shares_before"] == [34, 33, 33] and log[0]["shares_after"] == [25, 25, 25, 25]


def test_push_is_blocked_for_a_campaign_that_lost_our_prefix(http, fake):
    cid, sid = three_offers(fake)
    fetch(http, cid)
    add(http, sid, 105)
    fake.campaigns[cid]["name"] = "renamed_by_someone"
    assert push(http, sid, status=403)["detail"].startswith("Campaign 'renamed_by_someone'")
    assert writes(fake) == []