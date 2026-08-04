"""Reading the log directory.

Two processes write here — the bot and this panel — because a
TimedRotatingFileHandler renames the file it owns at midnight, and two of them
on one path lose records. So everything below deals in "which of the two", and
the answer is never taken from the caller.
"""
from datetime import datetime
from pathlib import Path

from core.settings import ADMIN_LOG_FILE_NAME, LOG_DIR, LOG_FILE_NAME

# The files being written to right now, as opposed to rotated archives. The
# bot's comes first: it is what the logs page opens on.
LIVE_LOG_NAMES = (LOG_FILE_NAME, ADMIN_LOG_FILE_NAME)


def log_directory():
    """The one place logs live.

    Everything that reads or serves them asks here, rather than importing
    `LOG_DIR` for itself. Two bindings to the same setting is one binding too
    many: the download route had its own, and served files out of a different
    directory from the one the allowlist was built from.
    """
    return Path(LOG_DIR).resolve()


def log_path(name=LOG_FILE_NAME):
    return log_directory() / name


def live_log_name(requested):
    """Which of the two live logs a request is asking for.

    Anything unrecognised falls back to the bot's, so a hand-typed `?file=` can
    never name a path of the caller's choosing.
    """
    return requested if requested in LIVE_LOG_NAMES else LOG_FILE_NAME


def log_files():
    """Both processes' logs: the current files first, then whatever the nightly
    rotation has left behind — those are named `<name>.YYYY-MM-DD`, so newest
    is last by name.

    This list is also the allowlist the download route checks against, so a
    file missing from here is a file that cannot be downloaded.
    """
    directory = log_directory()
    if not directory.exists():
        return []

    entries = []
    for live_name in LIVE_LOG_NAMES:
        for path in sorted(directory.glob(f"{live_name}*"), reverse=True):
            if not path.is_file():
                continue

            stat = path.stat()
            entries.append({
                "name": path.name,
                "size_kb": max(1, round(stat.st_size / 1024)),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M"),
                "current": path.name == live_name,
            })

    entries.sort(key=lambda entry: not entry["current"])

    return entries


def at_level(lines, level):
    """Lines of one severity. The level sits between two spaces in every
    formatted record, which is enough to match on without parsing."""
    if not level:
        return lines

    return [line for line in lines if f" {level} " in line]


def log_lines(count, path, level=None):
    if not path.exists():
        return []

    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-count * 4:]

    return [line.rstrip() for line in at_level(lines, level)[-count:]]


def recent_problems(count):
    """Warnings from both processes together.

    Every line opens with a timestamp in the same fixed-width format, so
    sorting them as plain strings is sorting them by time.
    """
    lines = []
    for name in LIVE_LOG_NAMES:
        lines += log_lines(count, log_path(name), level="WARNING")

    return sorted(lines)[-count:]
