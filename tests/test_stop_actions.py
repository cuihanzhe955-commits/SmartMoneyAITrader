from unittest.mock import Mock
import time

import pytest

from terminal.api import ProtectionAction
from test_stop_runtime import active
from test_hosted import detail


def ready(rt, ledger, old, venue):
    ledger.observe(old["client_id"], detail(old, state="canceled"))
    def admit(s):
        with rt.db.db:
            current=rt.db.load();current["admitted"]=True;rt.db.save(current)
        return True
    rt.admit=Mock(side_effect=admit)
    venue.client.load_markets=Mock(return_value=venue.client.markets)
    venue.audit_spot=Mock(return_value={"dedicated_balance_match":True})
    venue.algo_inventory=Mock(return_value=[])
    venue.quote=Mock(side_effect=lambda s:(100,101,time.time()))
    venue.client.privatePostTradeOrderAlgo=Mock(side_effect=lambda p:dict(code="0",data=[dict(sCode="0",algoId="new-algo",algoClOrdId=p["algoClOrdId"])]))


def test_runtime_create_cancel_release_roundtrip(active):
    rt,ledger,old,v=active
    ready(rt,ledger,old,v)
    cid=rt.db.load()["id"]
    order=rt.hosted_action(cid,"create",symbol="BTC",stop_price=90)
    assert order["stage"]=="ACCEPTED"
    assert rt.hosted_lane is None
    v.lookup_stop.return_value=detail(order,algoId="new-algo")
    rt.hosted_tick()
    assert rt.hosted_lane is not None and ledger.get(order["client_id"])["stage"]=="LIVE"
    v.client.privatePostTradeCancelAlgos=Mock(return_value=dict(code="0",data=[dict(sCode="0",algoId="new-algo")]))
    result=rt.hosted_action(cid,"cancel",order["client_id"])
    assert result["stage"]=="CANCEL_PENDING"
    v.lookup_stop.return_value=detail(order,algoId="new-algo",state="canceled",uTime="1001")
    assert rt.hosted_action(cid,"query",order["client_id"])["stage"]=="CANCELED"
    assert rt.hosted_action(cid,"finalize",order["client_id"])["released"]
    assert rt.db.load()["lifecycle_status"]=="PAUSED" and not rt.db.load()["admitted"]
    v.client.privatePostTradeOrderAlgo.assert_called_once()
    v.client.privatePostTradeCancelAlgos.assert_called_once()


def test_duplicate_click_and_submit_timeout_preserve_one_intent(active):
    rt,ledger,old,v=active
    ready(rt,ledger,old,v)
    v.client.privatePostTradeOrderAlgo.side_effect=TimeoutError("private-response")
    cid=rt.db.load()["id"]
    with pytest.raises(ValueError,match="提交结果未确认"):
        rt.hosted_action(cid,"create",symbol="BTC",stop_price=90)
    with pytest.raises(ValueError,match="禁止重复创建"):
        rt.hosted_action(cid,"create",symbol="BTC",stop_price=90)
    v.client.privatePostTradeOrderAlgo.assert_called_once()


def test_unsent_failed_preflight_draft_can_be_canceled_locally(active):
    rt,ledger,old,v=active
    ready(rt,ledger,old,v)
    v.quote.side_effect=TimeoutError()
    cid=rt.db.load()["id"]
    with pytest.raises(TimeoutError):rt.hosted_action(cid,"create",symbol="BTC",stop_price=90)
    drafts=[row for row in rt.hosted_status()["orders"] if row["stage"]=="PLANNED"]
    assert len(drafts)==1
    v.lookup_stop.reset_mock()
    assert rt.hosted_action(cid,"cancel",drafts[0]["client_id"])["stage"]=="CANCELED"
    v.lookup_stop.assert_not_called()
    v.client.privatePostTradeOrderAlgo.assert_not_called()


@pytest.mark.parametrize("mode",["live","paper"])
def test_action_never_opens_real_or_paper_write_path(active, mode):
    rt,ledger,o,v=active
    with rt.db.db:
        s=rt.db.load();s["config"]["execution"]=mode;rt.db.save(s)
    with pytest.raises(ValueError,match="只开放"):
        rt.hosted_action(s["id"],"create",symbol="BTC",stop_price=90)
    v.permission_check.assert_not_called()


@pytest.mark.parametrize("value",[0,-1,float("nan"),float("inf")])
def test_api_schema_rejects_invalid_stop_price(value):
    with pytest.raises(ValueError):ProtectionAction(id=1,action="create",symbol="BTC",stop_price=value)
