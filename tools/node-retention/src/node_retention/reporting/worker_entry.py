"""Internal parent-identity handshake before importing the reporting application."""

import os
import re
import sys


def main() -> None:
    expected = os.environ.get("NODE_RETENTION_REPORT_CONTROLLER_PID")
    if expected is None or re.fullmatch(r"[1-9][0-9]*", expected) is None or os.getppid() != int(expected):
        sys.stderr.write("report worker original parent is absent or unverifiable\n")
        raise SystemExit(2)
    # Native parent-death notification is established by setpriv before this exec.
    from node_retention.reporting.cli import app

    app(["--worker"])


if __name__ == "__main__":
    main()
