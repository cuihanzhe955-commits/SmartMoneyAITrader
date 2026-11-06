"""Event capability boundaries; contract presence never grants execution."""
from typing import Protocol


class EventMarketAdapter(Protocol):
    def discover_markets(self, query): ...
    def get_snapshot(self, query): ...
    def get_settlement(self, query): ...
    def submit_order(self, intent): ...
    def cancel_order(self, order): ...


class PolymarketResearchAdapter:
    def __init__(self, discovery, details):self.discovery,self.details=discovery,details
    def discover_markets(self,query):return self.discovery.run(query)
    def get_snapshot(self,query):return self.details.cost(query)
    def get_settlement(self,query):return self.details.resolution(query)
    cost=get_snapshot
    resolution=get_settlement
    def close(self):self.details.close()
    def submit_order(self,intent):raise ValueError("事件适配器仅限公开研究，真实订单未授权或验收")
    def cancel_order(self,order):raise ValueError("事件适配器不提供真实撤单操作")


class GateEventAdapter:
    """No guessed paths, private calls, automatic fallback or success stubs."""
    def capabilities(self):
        return dict(provider="gate",product="event",status="unverified",enabled=False,
            reason="普通账户事件专用API及权限尚未核验；现货与永续接口不能替代",
            operations={k:"unverified" for k in ("discover_markets","get_market_rules","subscribe_quotes","get_snapshot",
                "list_orders","list_fills","list_ledger","get_positions","get_settlement","submit_order","cancel_order")})
    def _blocked(self,*args,**kwargs):raise ValueError(self.capabilities()["reason"])
    discover_markets=get_market_rules=subscribe_quotes=get_snapshot=_blocked
    list_orders=list_fills=list_ledger=get_positions=get_settlement=_blocked
    submit_order=cancel_order=_blocked
