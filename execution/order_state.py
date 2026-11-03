"""Allowed transitions for the paper broker. The default fill policy is all-or-none."""

TRANSITIONS = {
    "CREATED": {"APPROVED", "REJECTED", "CANCELLED"},
    "APPROVED": {"SUBMITTED", "CANCELLED", "FAILED"},
    "SUBMITTED": {"FILLED", "PARTIALLY_FILLED", "CANCELLED", "FAILED"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "FAILED"},
    "FILLED": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
    "FAILED": set(),
}


def lifecycle(*states):
    if not states or states[0] != "CREATED":
        raise ValueError("订单必须从 CREATED 开始")
    for a, b in zip(states, states[1:]):
        if b not in TRANSITIONS[a]:
            raise ValueError(f"非法模拟订单状态 {a} → {b}")
    return list(states)
