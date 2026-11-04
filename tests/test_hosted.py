from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest

from execution.hosted import HostedStops


def state(**config):
    return dict(id=1, account_ref="fixture-account", cash=90,
                config=dict(exchange="okx", execution="demo", product="spot", **config),
                positions={"BTC": dict(qty=.1, cost=10, opened=1, opening_order="entry1")})


def detail(order, **changes):
    return {**dict(algoId="algo1", algoClOrdId=order["client_id"], instId="BTC-USDT",
                  instType="SPOT", tdMode="cash", side="sell", ordType="conditional",
                  sz="0.1", slTriggerPx="90", slOrdPx="-1", slTriggerPxType="last",
                  state="live", uTime="1000", ordIdList=[], actualSz="0"), **changes}


def ack(order, **changes):
    return dict(code="0", data=[dict(algoId="algo1", algoClOrdId=order["client_id"], sCode="0", **changes)])


@pytest.fixture
def ledger(tmp_path):
    stops = HostedStops(tmp_path / "ledger.db")
    try:
        yield stops
    finally:
        stops.close()


def sending(ledger):
    return ledger.begin_create(ledger.plan(state(), "BTC", 90)["client_id"], state())


def active(ledger):
    order = sending(ledger)
    return ledger.observe(order["client_id"], detail(order))


def test_intent_committed_before_send_and_restart_never_resends(tmp_path):
    path = tmp_path / "ledger.db"
    first = HostedStops(path)
    order = sending(first)
    first.close()  # crash after commit, before any response
    restored = HostedStops(path)
    try:
        cid = order["client_id"]
        assert restored.get(cid)["stage"] == "SENDING"
        assert restored.plan(state(), "BTC", 90)["client_id"] == cid
        with pytest.raises(ValueError, match="禁止重复"):
            restored.begin_create(cid, state())
        restored.uncertain(cid)
        assert restored.exit_blocked(cid)
        assert restored.observe(cid, detail(order))["stage"] == "LIVE"
        with pytest.raises(ValueError, match="重复创建"):
            restored.plan(state(), "BTC", 91)
    finally:
        restored.close()


def test_request_ack_is_not_protection_or_cancel_confirmation(ledger):
    order = sending(ledger)
    cid = order["client_id"]
    assert ledger.acknowledge(cid, ack(order))["stage"] == "ACCEPTED"
    assert ledger.exit_blocked(cid)
    ledger.observe(cid, detail(order))
    ledger.begin_cancel(cid)
    assert ledger.acknowledge(cid, ack(order), cancel=True)["stage"] == "CANCEL_PENDING"
    assert ledger.exit_blocked(cid)
    # Cancel timeout and a still-live query cannot restore a false protected label.
    ledger.uncertain(cid)
    assert ledger.observe(cid, detail(order, uTime="1001"))["stage"] == "CANCEL_PENDING"
    assert ledger.observe(cid, detail(order, state="canceled", uTime="1002"))["stage"] == "CANCELED"
    assert not ledger.exit_blocked(cid)


def test_cancel_trigger_race_requires_child_fill_reconciliation(ledger):
    order = active(ledger)
    cid = order["client_id"]
    ledger.begin_cancel(cid)
    result = ledger.observe(cid, detail(order, state="effective", uTime="1002", ordIdList=["child1"], actualSz="0.1"))
    assert result["stage"] == "TRIGGERED" and result["children"] == ["child1"]
    assert ledger.exit_blocked(cid)  # effective is not a fill or a flat account
    ledger.uncertain(cid)
    with pytest.raises(ValueError, match="终态回退"):
        ledger.observe(cid, detail(order, uTime="1003"))
    with pytest.raises(ValueError, match="重复创建"):
        ledger.plan(state(), "BTC", 89)


@pytest.mark.parametrize("changes", [
    {"algoClOrdId": "foreign"}, {"algoId": "foreign"}, {"instId": "ETH-USDT"},
    {"instType": "SWAP"}, {"tdMode": "cross"}, {"side": "buy"}, {"sz": "0.09"},
    {"sz": "NaN"}, {"slTriggerPx": "91"}, {"slOrdPx": "89"},
    {"slTriggerPxType": "mark"}, {"tpTriggerPx": "110"}, {"tgtCcy": "quote_ccy"},
    {"uTime": "999"}, {"uTime": "nan"}, {"state": "pause"},
    {"state": "effective"}, {"state": "canceled", "actualSz": "0.05"},
    {"state": "order_failed", "actualSz": None},
    {"state": "effective", "ordIdList": ["child1", "child1"]},
])
def test_foreign_stale_partial_or_ambiguous_detail_keeps_exit_blocked(ledger, changes):
    order = active(ledger)
    with pytest.raises(ValueError):
        ledger.observe(order["client_id"], detail(order, **changes))
    assert ledger.exit_blocked(order["client_id"])


@pytest.mark.parametrize("response", [None, {}, {"code": "0", "data": []},
    {"code": "0", "data": [None]}, {"code": "0", "data": [{"sCode": "51008", "algoId": "algo1"}]}])
def test_failed_create_cannot_be_retried_blindly(ledger, response):
    order = sending(ledger)
    with pytest.raises(ValueError):
        ledger.acknowledge(order["client_id"], response)
    with pytest.raises(ValueError, match="禁止重复"):
        ledger.begin_create(order["client_id"], state())
    assert ledger.exit_blocked(order["client_id"])


def test_failed_trigger_report_does_not_change_position_or_cash(ledger):
    before = state()
    order = active(ledger)
    assert ledger.observe(order["client_id"], detail(order, state="order_failed", uTime="1002"))["stage"] == "FAILED"
    assert state() == before


@pytest.mark.parametrize("field,value", [("execution", "live"), ("exchange", "binance"), ("product", "swap")])
def test_prototype_cannot_enable_live_or_unsupported_product(ledger, field, value):
    s = state()
    s["config"][field] = value
    with pytest.raises(ValueError, match="禁止启用真实资金"):
        ledger.plan(s, "BTC", 90)
    assert ledger.db.execute("SELECT count(*) FROM hosted_stops").fetchone()[0] == 0


def test_position_change_blocks_send_and_existing_order_blocks_cross_session(ledger):
    order = ledger.plan(state(), "BTC", 90)
    changed = state()
    changed["positions"]["BTC"]["qty"] = .05
    with pytest.raises(ValueError, match="持仓已变化"):
        ledger.begin_create(order["client_id"], changed)
    other = state()
    other["id"] = 2
    with pytest.raises(ValueError, match="重复创建"):
        ledger.plan(other, "BTC", 90)
    assert ledger.begin_cancel(order["client_id"])["stage"] == "CANCELED"


def test_same_quantity_with_new_owner_cannot_send_old_stop(ledger):
    order = ledger.plan(state(), "BTC", 90)
    changed = state()
    changed["positions"]["BTC"]["opening_order"] = "entry2"
    with pytest.raises(ValueError, match="持仓已变化"):
        ledger.begin_create(order["client_id"], changed)


def test_terminal_intent_cannot_silently_be_reused(ledger):
    order = active(ledger)
    ledger.observe(order["client_id"], detail(order, state="canceled", uTime="1002", actualSz="0.00000"))
    with pytest.raises(ValueError, match="相同保护意图已终结"):
        ledger.plan(state(), "BTC", 90)


@pytest.mark.parametrize("bad", [1, True, {}, ["algo1"], " "])
def test_non_string_or_blank_exchange_id_rejected(ledger, bad):
    order = sending(ledger)
    response = ack(order)
    response["data"][0]["algoId"] = bad
    with pytest.raises(ValueError):
        ledger.acknowledge(order["client_id"], response)
    with pytest.raises(ValueError):
        ledger.observe(order["client_id"], detail(order, algoId=bad))


def test_concurrent_planners_share_one_durable_intent(tmp_path):
    path = tmp_path / "ledger.db"
    first, second = HostedStops(path), HostedStops(path)
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda store: store.plan(state(), "BTC", 90), [first, second]))
        assert results[0]["client_id"] == results[1]["client_id"]
        assert first.db.execute("SELECT count(*) FROM hosted_stops").fetchone()[0] == 1
        first.begin_create(results[0]["client_id"], state())
        with pytest.raises(ValueError, match="禁止重复"):
            second.begin_create(results[0]["client_id"], state())
    finally:
        first.close()
        second.close()


def test_okx_signed_read_by_original_client_id_is_read_only(ledger):
    from test_acceptance import wire_venue
    venue = wire_venue()
    order = sending(ledger)
    calls = []
    def fetch(url, method, headers, body):
        calls.append((url, method, body))
        assert headers.get("OK-ACCESS-SIGN")
        return {"code": "0", "data": [detail(order)]}
    venue.client.fetch = fetch
    result = venue.lookup_stop(order["client_id"])
    assert ledger.observe(order["client_id"], result)["stage"] == "LIVE"
    url, method, body = calls[0]
    assert method == "GET" and body is None
    assert urlparse(url).path == "/api/v5/trade/order-algo"
    assert parse_qs(urlparse(url).query) == {"algoClOrdId": [order["client_id"]]}


@pytest.mark.parametrize("rows", [[], [None], [{"algoId": "foreign", "algoClOrdId": "other"}]])
def test_empty_or_foreign_query_is_unknown_not_canceled(rows):
    from test_acceptance import wire_venue
    venue = wire_venue()
    venue.client.fetch = lambda *a: {"code": "0", "data": rows}
    with pytest.raises(ValueError, match="禁止根据空清单"):
        venue.lookup_stop("spfixture")
