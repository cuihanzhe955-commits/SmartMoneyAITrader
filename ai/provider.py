import json
import time
from typing import Literal
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    symbol: str
    action: Literal["BUY", "SELL", "HOLD", "SKIP"]
    fraction: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
    risk: str = Field(min_length=1, max_length=300)
    exit_plan: str = Field(min_length=1, max_length=300)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Provider:
    def __init__(self, c, key):
        self.c = c
        self.key = key
        self.cancel = None
        self.deadline = None
        u = urlsplit(c["base"])
        if (
            u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or u.query
            or u.fragment
        ):
            raise ValueError("AI Base URL 必须为 HTTPS 服务地址")

    def chat(self, prompt, data):
        timeout = self.c["timeout"]
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0 or (self.cancel and self.cancel.is_set()):
            raise ValueError("模型任务已取消或超时")
        req = Request(
            self.c["base"].rstrip("/") + "/chat/completions",
            headers={
                "Authorization": "Bearer " + self.key,
                "Content-Type": "application/json",
            },
            data=json.dumps(
                dict(
                    model=self.c["model"],
                    messages=[
                        dict(role="system", content=prompt),
                        dict(role="user", content=json.dumps(data, ensure_ascii=False)),
                    ],
                    max_tokens=400,
                )
            ).encode(),
        )
        try:
            with build_opener(NoRedirect()).open(req, timeout=timeout) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except HTTPError as e:
            raise ValueError(f"模型接口返回 HTTP {e.code}") from None
        except Exception:
            raise ValueError("AI 请求失败，请检查连接、模型和预算") from None

    def propose(self, metrics, held):
        brief = self.chat(
            "你是市场分析员。依据提供的指标比较机会和风险，用简短中文回答。", metrics
        )
        raw = self.chat(
            "仅返回一个 JSON 对象。Schema: "
            + json.dumps(Advice.model_json_schema(), ensure_ascii=False),
            {"market": metrics, "analysis": brief, "held": list(held)},
        )
        advice = Advice.model_validate_json(raw)
        if advice.action != "SKIP" and advice.symbol not in {m["symbol"] for m in metrics}:
            raise ValueError("AI 提案币种不在候选池")
        return brief, advice
