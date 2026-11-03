from challenge.config import DEFAULT
from risk.parameters import validate_parameters, RECOMMENDED

# Historical import name retained for callers; these are recommendations only.
LIMITS = {key: (low, high) for key, (_, low, high) in RECOMMENDED.items()}
CHOICES = {
    "source": ["history", "public"],
    "settlement": ["mark", "close"],
    "speed": [1, 60, 120, 600, 3600],
    "preset": ["综合狂飙", "快速动量", "突破追踪"],
}


def config(body):
    if body.get("consent") is not True:
        raise ValueError("请先确认模拟实验风险")
    c = {k: body.get(k, v) for k, v in DEFAULT.items()}
    validate_parameters(c)
    for k, opts in CHOICES.items():
        if c[k] not in opts or (k == "speed" and type(c[k]) is not int):
            raise ValueError("参数无效 " + k)
    w = c["weights"]
    if (
        not isinstance(w, list)
        or len(w) != 5
        or any(type(x) not in (int, float) or not 0 <= x <= 100 for x in w)
        or sum(w) == 0
    ):
        raise ValueError("评分权重无效")
    if c["source"] == "public":
        c["speed"] = 1
    return c
