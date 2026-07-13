#!/usr/bin/env python3
"""Count inotify watches per process. Run while Local Lucy is running."""

from __future__ import annotations

import glob
from collections import Counter
from pathlib import Path


def count_watches_for_fd(fdinfo_path: Path) -> int:
    """Count inotify watches by counting 'inotify wd' entries in fdinfo."""
    try:
        text = fdinfo_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.strip().startswith("inotify wd"))


def main() -> int:
    totals: Counter[str] = Counter()
    for fdinfo in glob.glob("/proc/[0-9]*/fdinfo/*"):
        path = Path(fdinfo)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "inotify" not in text:
            continue
        parts = path.parts
        pid = parts[2]
        comm_path = Path(f"/proc/{pid}/comm")
        try:
            comm = comm_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            comm = "?"
        key = f"{pid} {comm}"
        totals[key] += count_watches_for_fd(path)

    print(f"{'WATCHES':>10}  PID  COMM")
    print("-" * 50)
    for key, count in totals.most_common(30):
        pid, comm = key.split(" ", 1)
        print(f"{count:>10}  {pid:>6}  {comm}")

    print("-" * 50)
    print(f"Total inotify watches: {sum(totals.values())}")
    print(f"Max user watches: {Path('/proc/sys/fs/inotify/max_user_watches').read_text().strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
