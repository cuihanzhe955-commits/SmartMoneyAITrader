"""Source checks shared by both local Windows HTTP servers."""
import re


def local_source(peer, host):
    return peer in ('127.0.0.1', '::1') and bool(
        re.fullmatch(r'(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?', host)
    )
