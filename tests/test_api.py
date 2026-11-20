def create(client, **kw):
    payload = {"name": "test camp", "country": "de", "offer_id": 1}
    payload.update(kw)
    return client.post("/api/campaigns", json=payload)


def test_create_campaign_builds_two_streams(client, fake):
    r = create(client)
    assert r.status_code == 201, r.text
    data = r.json()
    camp = fake.campaigns[data["keitaro_id"]]
    assert camp["domain_id"] == 1813 and camp["group_id"] == 9799 and camp["traffic_source_id"] == 836
    assert camp["alias"] and data["url"] == "https://example.com/" + camp["alias"]

    geo, offer = fake.streams[data["geo_stream_id"]], fake.streams[data["offer_stream_id"]]
    assert geo["position"] == 1 and geo["schema"] == "redirect"
    assert geo["action_payload"] == "https://www.google.com"
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["DE"]}]
    assert offer["position"] == 2 and offer["schema"] == "landings"
    assert [(o["offer_id"], o["share"]) for o in offer["offers"]] == [(1, 100)]

    listed = client.get("/api/campaigns/created").json()
    assert [c["keitaro_id"] for c in listed] == [data["keitaro_id"]]


def test_create_validates_input(client):
    assert create(client, country="Germany").status_code == 422
    assert create(client, name="   ").status_code == 422
    r = create(client, offer_id=999)
    assert r.status_code == 400 and "999" in r.json()["detail"]


def test_create_rolls_back_on_stream_failure(client, fake):
    fake.fail_stream_create = True
    r = create(client)
    assert r.status_code == 502
    assert fake.deleted == list(fake.campaigns)  # half-built campaign removed
    assert client.get("/api/campaigns/created").json() == []


def _setup(client, fake, offers=(1,)):
    """Create a campaign through the creator, then put `offers` into its offer stream in Keitaro."""
    data = create(client, offer_id=offers[0]).json()
    cid, sid = data["keitaro_id"], data["offer_stream_id"]
    shares = {1: [100], 2: [50, 50], 3: [34, 33, 33]}[len(offers)]
    fake.streams[sid]["offers"] = [{"offer_id": o, "share": sh, "state": "active"} for o, sh in zip(offers, shares)]
    state = client.post(f"/api/campaigns/{cid}/fetch").json()
    return cid, sid, state


def keitaro_shares(fake, sid):
    return {o["offer_id"]: o["share"] for o in fake.streams[sid]["offers"]}


def offers_of(stream):
    return {o["offer_id"]: (o["state"], o["share"]) for o in stream["offers"]}


def test_fetch_lists_all_streams(client, fake):
    cid, sid, state = _setup(client, fake, (1, 2, 3))
    geo, offer = state["streams"]
    # the stream without offers is listed but not parsed
    assert geo["is_offer_stream"] is False and geo["offers"] == []
    assert offer["id"] == sid and offer["dirty"] is False
    assert offers_of(offer) == {1: ("active", 34), 2: ("active", 33), 3: ("active", 33)}


def test_add_offer_is_a_draft_until_push(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2, 3))
    s = client.post(f"/api/streams/{sid}/offers", json={"offer_id": 4}).json()
    assert s["dirty"] is True and s["share_total"] == 100
    assert offers_of(s) == {1: ("active", 25), 2: ("active", 25), 3: ("active", 25), 4: ("active", 25)}
    assert keitaro_shares(fake, sid) == {1: 34, 2: 33, 3: 33}  # Keitaro untouched

    s = client.post(f"/api/streams/{sid}/push").json()
    assert s["dirty"] is False
    assert keitaro_shares(fake, sid) == {1: 25, 2: 25, 3: 25, 4: 25}
    hist = client.get(f"/api/campaigns/{cid}/history").json()
    assert hist[0]["before"] == {"1": 34, "2": 33, "3": 33} and hist[0]["offer_ids"] == [1, 2, 3, 4]


def test_cancel_drops_unpublished_changes(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2, 3))
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 4})
    client.delete(f"/api/streams/{sid}/offers/1")
    s = client.post(f"/api/streams/{sid}/cancel").json()
    assert s["dirty"] is False
    assert offers_of(s) == {1: ("active", 34), 2: ("active", 33), 3: ("active", 33)}


def test_remove_archives_offer_and_bring_back(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2, 3))
    s = client.delete(f"/api/streams/{sid}/offers/3").json()
    assert s["dirty"] is True
    assert offers_of(s) == {1: ("active", 50), 2: ("active", 50), 3: ("removed", 0)}

    client.post(f"/api/streams/{sid}/push")
    assert keitaro_shares(fake, sid) == {1: 50, 2: 50}  # gone from Keitaro...
    s = client.get(f"/api/campaigns/{cid}/streams").json()["streams"][1]
    assert offers_of(s)[3] == ("removed", 0) and s["dirty"] is False  # ...but kept in our archive

    s = client.post(f"/api/streams/{sid}/offers/3/restore").json()
    assert s["dirty"] is True and offers_of(s)[3] == ("active", 33)
    client.post(f"/api/streams/{sid}/push")
    assert keitaro_shares(fake, sid) == {1: 34, 2: 33, 3: 33}


def test_removing_unpublished_offer_deletes_it(client, fake):
    cid, sid, _ = _setup(client, fake, (1,))
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 2})
    s = client.delete(f"/api/streams/{sid}/offers/2").json()
    assert offers_of(s) == {1: ("active", 100)} and s["dirty"] is False


def test_refetch_marks_offers_deleted_in_keitaro_as_removed(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2, 3))
    fake.streams[sid]["offers"] = [{"offer_id": 1, "share": 100, "state": "active"}]  # edited in Keitaro
    s = client.post(f"/api/campaigns/{cid}/fetch").json()["streams"][1]
    assert offers_of(s) == {1: ("active", 100), 2: ("removed", 0), 3: ("removed", 0)}
    assert s["dirty"] is False

    s = client.post(f"/api/streams/{sid}/offers/2/restore").json()
    assert offers_of(s)[1] == ("active", 50) and offers_of(s)[2] == ("active", 50)


def test_pinned_share_survives_rebalance(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2, 3))
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 4})  # 25 x4
    client.post(f"/api/streams/{sid}/push")
    s = client.patch(f"/api/streams/{sid}/offers/1", json={"pinned": True}).json()
    assert offers_of(s)[1] == ("active", 25)

    s = client.delete(f"/api/streams/{sid}/offers/4").json()
    assert offers_of(s) == {1: ("active", 25), 2: ("active", 38), 3: ("active", 37), 4: ("removed", 0)}
    s = client.post(f"/api/streams/{sid}/offers/4/restore").json()
    assert offers_of(s) == {1: ("active", 25), 2: ("active", 25), 3: ("active", 25), 4: ("active", 25)}

    # typing a share pins it
    s = client.patch(f"/api/streams/{sid}/offers/2", json={"share": 45}).json()
    assert offers_of(s) == {1: ("active", 25), 2: ("active", 45), 3: ("active", 15), 4: ("active", 15)}
    assert {o["offer_id"] for o in s["offers"] if o["pinned"]} == {1, 2}

    # pins can't exceed 100%
    assert client.patch(f"/api/streams/{sid}/offers/3", json={"share": 40}).status_code == 400
    client.post(f"/api/streams/{sid}/push")
    assert keitaro_shares(fake, sid) == {1: 25, 2: 45, 3: 15, 4: 15}


def test_push_validation_and_conflict(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2))
    client.delete(f"/api/streams/{sid}/offers/1")
    client.delete(f"/api/streams/{sid}/offers/2")
    r = client.post(f"/api/streams/{sid}/push")
    assert r.status_code == 400 and "хотя бы один" in r.json()["detail"]
    client.post(f"/api/streams/{sid}/cancel")

    client.patch(f"/api/streams/{sid}/offers/1", json={"share": 60})
    client.patch(f"/api/streams/{sid}/offers/2", json={"share": 30})  # all pinned, sum 90
    assert client.post(f"/api/streams/{sid}/push").status_code == 400

    client.patch(f"/api/streams/{sid}/offers/2", json={"pinned": False})  # -> 60/40
    fake.streams[sid]["offers"][0]["share"] = 10  # someone changed Keitaro meanwhile
    assert client.post(f"/api/streams/{sid}/push").status_code == 409


def test_editor_errors(client, fake):
    cid, sid, state = _setup(client, fake, (1,))
    geo_id = state["streams"][0]["id"]
    assert client.post(f"/api/streams/{sid}/offers", json={"offer_id": 777}).status_code == 404
    assert client.post(f"/api/streams/{sid}/offers", json={"offer_id": 1}).status_code == 400
    assert client.post(f"/api/streams/{geo_id}/offers", json={"offer_id": 2}).status_code == 400
    assert client.post("/api/streams/999999/offers", json={"offer_id": 2}).status_code == 404
    assert client.get("/api/campaigns/424242/streams").status_code == 404


def test_offer_search(client, fake):
    assert [o["id"] for o in client.get("/api/offers/search?q=offer b").json()] == [2]
    assert [o["id"] for o in client.get("/api/offers/search?q=3").json()] == [3]


def test_stats_and_totals(client, fake):
    cid, sid, _ = _setup(client, fake, (1, 2))
    fake.report_rows = [
        {"stream_id": sid, "offer_id": 1, "clicks": 100, "conversions": 5, "revenue": 50, "cost": 20, "profit": 30},
        {"stream_id": sid, "offer_id": 2, "clicks": "300", "conversions": 3, "revenue": "10", "cost": 40, "profit": -30},
    ]
    st = client.get(f"/api/campaigns/{cid}/stats?interval=all_time").json()
    o1 = st["streams"][str(sid)]["1"]
    assert o1["cr"] == 5.0 and o1["roi"] == 150.0
    t = st["totals"][str(sid)]
    assert t["clicks"] == 400 and t["conversions"] == 8 and t["profit"] == 0 and t["cr"] == 2.0 and t["roi"] == 0.0
    assert client.get(f"/api/campaigns/{cid}/stats?interval=forever").status_code == 400
