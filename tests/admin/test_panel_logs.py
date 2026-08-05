"""The logs page, its live tail, and downloading a file.

The download route is the one place the panel serves a file from disk, so the
allowlist it checks against is worth pinning down.
"""
import json
import logging

from admin import logfiles
from core.settings import ADMIN_LOG_FILE_NAME, LOG_FILE_NAME
from core.logs import ROOT_LOGGER_NAME, alert_handler, configure_logging

WARNING_LINE = "2026-03-11 09:30:00 WARNING  bot.services.cohort | cohort is full"
INFO_LINE = "2026-03-11 09:31:00 INFO     bot.services.questions | sent question"
PANEL_LINE = "2026-03-11 09:32:00 WARNING  bot.admin.app | failed admin sign-in"


def _write_log(log_dir, *lines, name=LOG_FILE_NAME):
    """`newline=""` so Windows doesn't turn every \\n into \\r\\n — the byte
    offsets the tail deals with are what several of these tests assert on, and
    production writes plain \\n."""
    path = log_dir / name

    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")

    return path


def test_logs_page_renders_with_no_files_yet(client, log_dir):
    response = client.get("/logs")

    assert response.status_code == 200
    assert "Порожньо." in response.get_data(as_text=True)


def test_logs_page_shows_the_lines(client, log_dir):
    _write_log(log_dir, INFO_LINE, WARNING_LINE)

    body = client.get("/logs").get_data(as_text=True)

    assert "sent question" in body
    assert "cohort is full" in body


def test_the_level_filter_narrows_the_lines(client, log_dir):
    _write_log(log_dir, INFO_LINE, WARNING_LINE)

    body = client.get("/logs?level=WARNING").get_data(as_text=True)

    assert "cohort is full" in body
    assert "sent question" not in body


def test_rotated_files_are_listed_with_the_current_one_first(client, log_dir):
    _write_log(log_dir, INFO_LINE)
    _write_log(log_dir, INFO_LINE, name=f"{LOG_FILE_NAME}.2026-03-10")

    body = client.get("/logs").get_data(as_text=True)

    assert LOG_FILE_NAME in body
    assert f"{LOG_FILE_NAME}.2026-03-10" in body
    assert "поточний" in body


# --- the live tail ---------------------------------------------------------

def test_tail_returns_nothing_when_there_is_no_file(client, log_dir):
    payload = json.loads(client.get("/logs/tail").get_data(as_text=True))

    assert payload == {"offset": 0, "lines": []}


def test_tail_returns_what_arrived_after_the_offset(client, log_dir):
    path = _write_log(log_dir, INFO_LINE)
    offset = path.stat().st_size

    _write_log(log_dir, INFO_LINE, WARNING_LINE)

    payload = json.loads(client.get(f"/logs/tail?offset={offset}").get_data(as_text=True))

    assert payload["lines"] == [WARNING_LINE]
    assert payload["offset"] > offset


def test_tail_stops_at_the_last_complete_line(client, log_dir):
    """A half-written line must not be shown, and the next poll must not start
    mid-character."""
    with (log_dir / LOG_FILE_NAME).open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"{INFO_LINE}\nhalf a li")

    payload = json.loads(client.get("/logs/tail?offset=0").get_data(as_text=True))

    assert payload["lines"] == [INFO_LINE]
    assert payload["offset"] == len(INFO_LINE.encode()) + 1


def test_tail_recovers_when_the_file_has_rotated_under_it(client, log_dir):
    """Midnight rotation leaves the browser's offset past the end of a fresh
    file; the tail restarts rather than returning nothing forever."""
    _write_log(log_dir, INFO_LINE)

    payload = json.loads(client.get("/logs/tail?offset=999999").get_data(as_text=True))

    assert payload["lines"] == [INFO_LINE]


def test_tail_applies_the_level_filter(client, log_dir):
    _write_log(log_dir, INFO_LINE, WARNING_LINE)

    payload = json.loads(
        client.get("/logs/tail?offset=0&level=WARNING").get_data(as_text=True)
    )

    assert payload["lines"] == [WARNING_LINE]


# --- downloading -----------------------------------------------------------

def test_downloading_the_current_log(client, log_dir):
    _write_log(log_dir, WARNING_LINE)

    response = client.get(f"/logs/download/{LOG_FILE_NAME}")

    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert "cohort is full" in response.get_data(as_text=True)


def test_downloading_a_rotated_file(client, log_dir):
    _write_log(log_dir, INFO_LINE, name=f"{LOG_FILE_NAME}.2026-03-10")

    assert client.get(f"/logs/download/{LOG_FILE_NAME}.2026-03-10").status_code == 200


def test_a_file_that_is_not_listed_cannot_be_downloaded(client, log_dir):
    """The route serves only names it listed itself, never a caller-supplied
    path — so nothing outside the log directory is reachable."""
    _write_log(log_dir, INFO_LINE)
    (log_dir.parent / "secret.txt").write_text("BOT_TOKEN=...", encoding="utf-8")

    assert client.get("/logs/download/secret.txt").status_code == 404
    assert client.get("/logs/download/../secret.txt").status_code in (301, 404)
    assert client.get("/logs/download/nothing.log").status_code == 404


# --- reading from the end --------------------------------------------------

def test_only_the_last_lines_are_read(log_dir):
    """It used to read the whole file and then slice, so the dashboard got
    slower every hour and only recovered when the log rotated at midnight."""
    _write_log(log_dir, *[f"line {index}" for index in range(5000)])

    assert logfiles.tail(log_dir / LOG_FILE_NAME, 3) == [
        "line 4997", "line 4998", "line 4999",
    ]


def test_a_short_file_is_returned_whole(log_dir):
    _write_log(log_dir, "only one")

    assert logfiles.tail(log_dir / LOG_FILE_NAME, 100) == ["only one"]


def test_an_empty_file_reads_as_nothing(log_dir):
    (log_dir / LOG_FILE_NAME).write_bytes(b"")

    assert logfiles.tail(log_dir / LOG_FILE_NAME, 10) == []


def test_a_line_spanning_a_block_boundary_is_not_torn(log_dir):
    """The read walks backwards in blocks, so a long line is reassembled from
    more than one of them."""
    long_line = "x" * 20000
    _write_log(log_dir, "before", long_line, "after")

    assert logfiles.tail(log_dir / LOG_FILE_NAME, 2, block_size=512) == [
        long_line, "after",
    ]


def test_multibyte_characters_survive_the_block_boundary(log_dir):
    """Cyrillic is two bytes a character, so a block can begin mid-character."""
    lines = [f"рядок номер {index}" for index in range(400)]
    _write_log(log_dir, *lines)

    assert logfiles.tail(log_dir / LOG_FILE_NAME, 2, block_size=64) == lines[-2:]


# --- the panel's own log ---------------------------------------------------
#
# The panel is a separate process and writes a separate file. It has to: a
# TimedRotatingFileHandler renames the file it owns at midnight, so two
# processes on one path lose each other's records. Which means the page has to
# be able to show both, or half the story is invisible.

def test_the_panel_log_can_be_read(client, log_dir):
    _write_log(log_dir, PANEL_LINE, name=ADMIN_LOG_FILE_NAME)

    body = client.get(f"/logs?file={ADMIN_LOG_FILE_NAME}").get_data(as_text=True)

    assert "failed admin sign-in" in body


def test_an_unknown_file_falls_back_to_the_bot_log(client, log_dir):
    """`?file=` picks between two known names and never names a path."""
    _write_log(log_dir, INFO_LINE)

    body = client.get("/logs?file=../../.env").get_data(as_text=True)

    assert "sent question" in body


def test_the_tail_follows_whichever_file_is_open(client, log_dir):
    _write_log(log_dir, INFO_LINE)
    _write_log(log_dir, PANEL_LINE, name=ADMIN_LOG_FILE_NAME)

    payload = json.loads(
        client.get(f"/logs/tail?offset=0&file={ADMIN_LOG_FILE_NAME}").get_data(as_text=True)
    )

    assert payload["lines"] == [PANEL_LINE]


def test_both_logs_are_listed_and_downloadable(client, log_dir):
    _write_log(log_dir, INFO_LINE)
    _write_log(log_dir, PANEL_LINE, name=ADMIN_LOG_FILE_NAME)

    body = client.get("/logs").get_data(as_text=True)

    assert LOG_FILE_NAME in body
    assert ADMIN_LOG_FILE_NAME in body
    assert client.get(f"/logs/download/{ADMIN_LOG_FILE_NAME}").status_code == 200


def test_the_dashboard_shows_warnings_from_both(client, log_dir):
    """Admin actions used to be invisible here no matter what went wrong."""
    _write_log(log_dir, WARNING_LINE)
    _write_log(log_dir, PANEL_LINE, name=ADMIN_LOG_FILE_NAME)

    body = client.get("/").get_data(as_text=True)

    assert "cohort is full" in body
    assert "failed admin sign-in" in body


def test_configure_logging_can_write_a_separate_file(tmp_path, monkeypatch):
    """The wiring itself: `admin_panel.py` passes its own filename and turns
    alerts off, since only the bot process has an event loop to send from."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr("core.logs.LOG_DIR", str(tmp_path))

    configure_logging(file_name=ADMIN_LOG_FILE_NAME, alerts=False)
    created = list(root.handlers)

    try:
        assert created, "configure_logging attached nothing"
        assert alert_handler not in created

        logging.getLogger(f"{ROOT_LOGGER_NAME}.admin").warning("panel started")
        for handler in created:
            handler.flush()

        written = (tmp_path / ADMIN_LOG_FILE_NAME)
        assert written.exists()
        assert "panel started" in written.read_text(encoding="utf-8")
        assert not (tmp_path / LOG_FILE_NAME).exists()
    finally:
        for handler in created:
            handler.close()


def test_the_panel_routes_flask_errors_to_the_same_handlers(app):
    """Flask logs unhandled exceptions to `app.logger`, which sits outside the
    "bot" namespace — so without this a 500 would leave no trace at all."""
    root = logging.getLogger(ROOT_LOGGER_NAME)

    if root.handlers:
        assert app.logger.handlers == root.handlers
    else:
        # Nothing configured under test, and the panel must leave Flask's own
        # default alone rather than silencing it.
        assert app.logger.propagate is True
