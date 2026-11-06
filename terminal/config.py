from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from challenge.config import DEFAULT
from strategy.ensemble import NAMES
from risk.parameters import validate_parameters, recommendations
from market.admission import ScannerConfig


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    profile: Literal["normal", "challenge"] = "normal"
    engine: Literal["rules", "ai"] = "rules"
    execution: Literal["paper", "demo", "live"] = "paper"
    exchange: Literal["okx", "binance", "gate"] = "okx"
    product: Literal["spot", "swap"] = "spot"
    source: Literal["history", "public", "csv"] = "history"
    dataset: str = ""
    market_mode: Literal["fixed", "dynamic"] = "fixed"
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    consent: bool = False
    confirmation: str = ""
    capital: float = Field(1000, strict=True)
    speed: Literal[1, 5, 20, 60, 100, 120, 600, 3600] = 120
    leverage: int = Field(1, ge=1, le=5)
    target: float | None = Field(None, strict=True)
    risk_per_trade_pct: float = Field(1, strict=True)
    interval: int | None = Field(None, strict=True)
    candidates: int | None = Field(None, strict=True)
    slots: int | None = Field(None, strict=True)
    utilization: float | None = Field(None, strict=True)
    concentration: float | None = Field(None, strict=True)
    stop: float | None = Field(None, strict=True)
    profit: float | None = Field(None, strict=True)
    trail: float | None = Field(None, strict=True)
    cooldown: int | None = Field(None, strict=True)
    fee: float | None = Field(None, strict=True)
    frame: int | None = Field(None, strict=True)
    trend: int | None = Field(None, strict=True)
    breaker: float | None = Field(None, strict=True)
    loss_limit: float = Field(20, strict=True)
    decision_interval: int = Field(60, strict=True)
    strategies: list[str] = Field(default_factory=lambda: list(NAMES))
    strict_min: float = Field(1, strict=True)
    paper_rules: Literal["micro", "venue"] = "micro"
    settlement: Literal["mark", "close"] = "mark"

    @model_validator(mode="after")
    def validate_session(self):
        if not self.consent:
            raise ValueError("请确认运行配置")
        if self.profile == "challenge" and self.engine != "rules":
            raise ValueError("24 小时挑战使用规则引擎；请在普通会话中选择 AI 交易")
        if not self.strategies or set(self.strategies) - set(NAMES):
            raise ValueError("策略选择无效")
        if self.execution != "paper" and (
            self.source != "public" or self.settlement != "mark"
        ):
            raise ValueError("交易所执行必须使用实时行情和保留仓位结算")
        if self.execution == "live" and self.confirmation != "启用实盘":
            raise ValueError("需输入「启用实盘」确认真实账户")
        if self.source != "public" and self.product != "spot":
            raise ValueError("内置归档和 CSV 为现货数据")
        if self.market_mode == "dynamic" and (self.execution != "paper" or self.source != "public" or self.product != "spot"):
            raise ValueError("动态候选仅适用于公开现货行情的模拟会话")
        if self.market_mode == "dynamic" and self.paper_rules != "micro":
            raise ValueError("动态模拟使用公开规则复核，不能混用历史归档撮合规则")
        from execution.platforms import require_session
        require_session(self.settings())
        validate_parameters(self.settings())
        return self

    def settings(self):
        base = dict(DEFAULT)
        if self.profile == "normal":
            base.update(
                target=12,
                utilization=60,
                concentration=20,
                slots=4,
                stop=2,
                profit=4,
                breaker=12,
                cooldown=180,
            )
        base.update(
            self.model_dump(exclude={"confirmation", "consent"}, exclude_none=True)
        )
        if self.source == "public":
            base["speed"] = 1
        return base

    def warnings(self):
        return recommendations(self.settings())
