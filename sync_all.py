"""
Daily runner for the Windows scheduled task: import everything the external chats produced.

Runs each importer in sequence, appends a timestamped report to sync.log, and never lets one
failure stop the others. All three importers are idempotent, so running this twice costs
nothing and fixes nothing twice.
"""

import io
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
LOG = HERE / "sync.log"
IMAGES = r"C:\Users\hp\OneDrive\Documents\Claude\Projects\Growmated\Social Posts\images"

STEPS = [
    ("content", [sys.executable, str(HERE / "sync_content.py"), "--apply"]),
    ("images", [sys.executable, str(HERE / "sync_images.py"), IMAGES, "--apply"]),
    ("emails", [sys.executable, str(HERE / "sync_emails.py"), "--apply"]),
    # Re-derive learned rules from outcome data, so tomorrow's copy uses yesterday's lessons.
    ("learnings", [sys.executable, str(HERE / "learnings.py")]),
]


def main() -> int:
    out = io.StringIO()
    out.write(f"\n===== sync_all {datetime.now():%Y-%m-%d %H:%M} =====\n")
    worst = 0
    for name, cmd in STEPS:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=HERE, timeout=900)
            tail = "\n".join((result.stdout or "").strip().splitlines()[-6:])
            out.write(f"[{name}] exit={result.returncode}\n{tail}\n")
            if result.returncode:
                out.write((result.stderr or "").strip()[-400:] + "\n")
                worst = 1
        except Exception as exc:
            out.write(f"[{name}] CRASHED: {type(exc).__name__}: {exc}\n")
            worst = 1

    report = out.getvalue()
    print(report)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(report)
    return worst


if __name__ == "__main__":
    sys.exit(main())
