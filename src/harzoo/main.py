"""编程智能体入口。"""

from __future__ import annotations

import sys
from pathlib import Path

from harzoo.agent.start import start
from harzoo.setup import run_setup
from harzoo.tui import run_tui


def main() -> None:
    """程序入口"""

    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        run_setup()
        return

    config_root = (Path.home() / ".harzoo" / "config").resolve()

    queue_in, queue_out, permission_gate = start(config_root)

    run_tui(queue_in=queue_in, queue_out=queue_out, permission_gate=permission_gate)


if __name__ == "__main__":
    main()
