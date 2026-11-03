import time


def market_time(s):
    return (
        min(
            s["deadline"],
            int(s["start"] + max(0, time.time() - s["anchor"]) * s["config"]["speed"]),
        )
        if s["anchor"]
        else s["start"]
    )
