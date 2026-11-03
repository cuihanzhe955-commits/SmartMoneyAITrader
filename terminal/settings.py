import json
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
import win32crypt


class AIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base: str = "https://api.openai.com/v1"
    model: str = ""
    timeout: int = Field(15, ge=2, le=60)
    interval: int = Field(120, ge=30, le=3600)
    calls: int = Field(40, ge=2, le=10000)
    ttl: int = Field(90, ge=1, le=120)
    fallback: Literal["rules", "hold", "manual"] = "rules"


class Vault:
    def __init__(self, path):
        self.path = Path(path)
        self.values = (
            json.loads(
                win32crypt.CryptUnprotectData(
                    self.path.read_bytes(), None, None, None, 0
                )[1]
            )
            if self.path.exists()
            else {}
        )

    def update(self, k, obj):
        self.update_many({k: obj})

    def update_many(self, updates):
        existing = {**self.values, **updates}
        encrypted = win32crypt.CryptProtectData(
            json.dumps(existing).encode(), "Smart Money Terminal", None, None, None, 0
        )
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(encrypted)
        os.replace(tmp, self.path)
        self.values = existing

    def public(self):
        return dict(
            ai=self.values.get("ai_config", AIConfig().model_dump()),
            ai_ready=bool(self.values.get("ai_key")),
            accounts=[k for k in self.values if k.startswith(("okx/", "binance/"))],
        )
