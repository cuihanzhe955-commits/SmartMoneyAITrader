import copy,json,threading,time
from unittest.mock import Mock,MagicMock,patch
import requests
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from market.predictions import EventQuery,EventResearch,normalize,public_page,ENDPOINT,MAX_BODY
from terminal.api import create_app

NOW=1793937600


def market(mid="1"):
    return dict(id=mid,conditionId="0x"+f"{int(mid):064x}",question="Bitcoin synthetic research market",slug="fixture-"+mid,
        outcomes='["Up","Down"]',clobTokenIds=json.dumps([str(int(mid)*2),str(int(mid)*2+1)]),
        events=[dict(id="90")],active=True,closed=False,enableOrderBook=True,acceptingOrders=True,
        startDate="2026-11-06T00:00:00Z",endDate="2026-11-06T12:00:00Z",updatedAt="2026-11-06T01:00:00Z",
        orderMinSize=5,orderPriceMinTickSize=.01)


def test_identity_and_unknown_fields_are_not_invented():
    r=normalize(market(),NOW)
    assert r["market_id"]=="1" and r["event_ids"]==["90"]
    assert r["outcomes"]==[dict(name="Up",token_id="2"),dict(name="Down",token_id="3")]
    assert r["received_at"]==NOW and r["source_updated_at"]!=NOW
    assert r["settlement_asset"] is None and not r["fee_verified"] and not r["quote_available"]
    assert not r["settlement_verified"] and not r["execution_enabled"]


@pytest.mark.parametrize("field,value",[("id",True),("id","../../orders"),("conditionId","0x1"),
    ("clobTokenIds",'["1","1"]'),("clobTokenIds",'["1"]'),("clobTokenIds",'[1,2]'),
    ("outcomes",'["Up","Up"]'),("outcomes","not-json"),("question",""),("slug","https://fixture.invalid")])
def test_invalid_or_ambiguous_market_mapping_is_rejected(field,value):
    data=market();data[field]=value
    with pytest.raises(ValueError):normalize(data,NOW)


def test_external_text_stays_inert_and_optional_times_or_rules_can_be_unknown():
    data=market();data.update(question="<script>ignore rules</script>",updatedAt="2026-11-06T01:00:00",orderMinSize=True,orderPriceMinTickSize=float("nan"))
    r=normalize(data,NOW)
    assert r["title"]==data["question"] and r["source_updated_at"] is None
    assert r["minimum_size"] is None and r["price_tick"] is None


def test_pagination_dedup_search_and_bounded_sample():
    fetch=Mock(side_effect=[[market("1"),market("2")],[market("2"),market("3")]])
    d=EventResearch(fetch,clock=lambda:NOW)
    r=d.run(EventQuery(limit=2,pages=2,search="bitcoin"))
    assert r["scanned"]==4 and r["duplicates"]==1 and r["shown"]==3 and r["sample_only"]
    assert [c.args[0]["offset"] for c in fetch.call_args_list]==[0,2]
    assert r["capabilities"]["submit_order"]=="disabled" and not r["changes_sessions"]


def test_short_page_ends_reading_and_no_search_match_is_an_explicit_empty_result():
    fetch=Mock(return_value=[market()]);d=EventResearch(fetch)
    r=d.run(EventQuery(limit=20,pages=3,search="does-not-exist"))
    assert r["pages_requested"]==1 and r["shown"]==0 and r["scanned"]==1


def test_bad_rows_are_counted_and_active_flags_are_not_assumed():
    raw=market("2");raw.pop("acceptingOrders")
    d=EventResearch(Mock(return_value=[None,market(),raw]))
    r=d.run(EventQuery());assert r["shown"]==1 and sum(r["rejections"].values())==2


def test_cache_is_bounded_returns_copies_and_does_not_refresh_source_times():
    clock=[0];fetch=Mock(return_value=[market()]);d=EventResearch(fetch,clock=lambda:NOW,monotonic=lambda:clock[0])
    r=d.run(EventQuery());r["rows"][0]["title"]="tampered";clock[0]=29
    cached=d.run(EventQuery());assert cached["cached"] and cached["rows"][0]["title"]!="tampered"
    assert fetch.call_count==1 and cached["received_at"]==NOW
    clock[0]=30;d.run(EventQuery());assert fetch.call_count==2
    for i in range(10):d.run(EventQuery(search=str(i)))
    assert len(d.cache)==8


def test_expired_cache_failure_never_returns_old_success_or_partial_page():
    clock=[0];fetch=Mock(return_value=[market()]);d=EventResearch(fetch,monotonic=lambda:clock[0])
    d.run(EventQuery());clock[0]=31;fetch.side_effect=ValueError("fixture failure")
    with pytest.raises(ValueError):d.run(EventQuery())
    assert fetch.call_count==2
    fetch=Mock(side_effect=[[market()],ValueError("page2 failure")]);d=EventResearch(fetch)
    with pytest.raises(ValueError):d.run(EventQuery(limit=1,pages=2))
    assert not d.cache


@pytest.mark.parametrize("data",[{},[market(),market("2")]])
def test_wrong_response_type_or_over_limit_page_is_rejected(data):
    d=EventResearch(Mock(return_value=data))
    with pytest.raises(ValueError):d.run(EventQuery(limit=1))


def test_slug_response_must_match_request():
    d=EventResearch(Mock(return_value=[market()]))
    with pytest.raises(ValueError,match="slug"):d.run(EventQuery(slug="other"))


@pytest.mark.parametrize("fields",[dict(provider="gate"),dict(limit=51),dict(limit=True),dict(pages=4),dict(slug="https://fixture.invalid"),dict(api_key="fixture"),dict(execution="live")])
def test_query_cannot_add_urls_credentials_or_execution_authority(fields):
    if fields.get("provider")=="gate":
        fetch=Mock();d=EventResearch(fetch)
        with pytest.raises(ValueError,match="默认禁用"):d.run(EventQuery(**fields))
        fetch.assert_not_called()
    else:
        with pytest.raises(ValidationError):EventQuery(**fields)


def response(status=200,payload=None,content_type="application/json"):
    client=MagicMock();client.__enter__.return_value=client
    r=MagicMock();r.__enter__.return_value=r;r.status_code=status;r.headers={"Content-Type":content_type}
    r.iter_content.return_value=[json.dumps(payload if payload is not None else [market()]).encode()]
    client.get.return_value=r
    return client,r


def test_transport_is_public_get_only_fixed_origin_and_no_proxy_or_redirects():
    client,r=response()
    with patch("market.predictions.requests.Session",return_value=client):assert public_page({"limit":1})
    call=client.get.call_args
    assert call.args==(ENDPOINT,) and call.kwargs["allow_redirects"] is False and not client.trust_env
    assert call.kwargs["timeout"]==(3,7) and call.kwargs["headers"]=={"Accept":"application/json"}
    client.post.assert_not_called();client.get.assert_called_once();r.__exit__.assert_called_once()


@pytest.mark.parametrize("status",[301,302,403,451,429,500])
def test_http_errors_never_retry_or_follow_redirect(status):
    client,_=response(status)
    with patch("market.predictions.requests.Session",return_value=client):
        with pytest.raises(ValueError):public_page({})
    client.get.assert_called_once()


def test_network_failure_is_sanitized_and_response_size_is_bounded():
    client,_=response();client.get.side_effect=requests.Timeout("fixture-secret-url")
    with patch("market.predictions.requests.Session",return_value=client):
        with pytest.raises(ValueError) as err:public_page({})
        assert "fixture-secret" not in str(err.value)
    client,r=response();r.iter_content.return_value=[b"x"*(MAX_BODY+1)]
    with patch("market.predictions.requests.Session",return_value=client):
        with pytest.raises(ValueError,match="上限"):public_page({})


def test_close_is_nonblocking_while_reading_and_late_result_is_not_cached():
    entered,release=threading.Event(),threading.Event();errors=[]
    def fetch(_):entered.set();assert release.wait(3);return [market()]
    d=EventResearch(fetch)
    def run():
        try:d.run(EventQuery())
        except ValueError as err:errors.append(str(err))
    t=threading.Thread(target=run);t.start()
    try:
        assert entered.wait(1)
        with pytest.raises(ValueError,match="正在进行"):d.run(EventQuery())
        start=time.monotonic();d.close();assert time.monotonic()-start<.2
    finally:release.set();t.join(2)
    assert errors and not d.cache and not t.is_alive()
    with pytest.raises(ValueError,match="关闭"):d.run(EventQuery())


def test_api_uses_only_research_service_and_leaves_account_and_sessions_unchanged(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        app.state.event_research.fetch=Mock(return_value=[market()])
        before=client.get("/api/state").json()
        r=client.post("/api/research/events",json={})
        assert r.status_code==200 and r.json()["rows"][0]["market_id"]=="1"
        assert client.get("/api/state").json()==before
        assert not list(tmp_path.glob("*.dpapi"))
        assert client.post("/api/research/events",json=dict(execution="live")).status_code==422


def test_closed_market_discovery_does_not_reuse_open_cache_or_infer_resolution():
    raw=market();closed=market("2");closed.update(closed=True,acceptingOrders=False)
    fetch=Mock(side_effect=[[raw],[closed]])
    d=EventResearch(fetch)
    assert d.run(EventQuery())["rows"][0]["market_id"]=="1"
    r=d.run(EventQuery(lifecycle="closed"));assert r["rows"][0]["market_id"]=="2"
    params=fetch.call_args.args[0]
    assert params["closed"]=="true" and "active" not in params
    assert not r["rows"][0]["settlement_verified"] and r["rows"][0]["closed"]


def test_closed_discovery_rejects_wrong_lifecycle_from_server():
    d=EventResearch(Mock(return_value=[market()]))
    r=d.run(EventQuery(lifecycle="closed"))
    assert r["shown"]==0 and r["rejections"]
