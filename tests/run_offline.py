"""Run the terminal tests without external connections or access to real runtime data."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
sys.dont_write_bytecode = True


def guard(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.sendto"):
        address = args[-1]
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("验收禁止外部连接")


if __name__ == "__main__":
    import pytest
    sys.addaudithook(guard)
    sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", *(sys.argv[1:] or ["tests"])]))
