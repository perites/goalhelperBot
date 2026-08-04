"""The logs page, its live tail, and downloading a file."""
from flask import abort, jsonify, render_template, request, send_from_directory

from admin.auth import login_required
from admin.logfiles import (
    LIVE_LOG_NAMES,
    at_level,
    live_log_name,
    log_directory,
    log_files,
    log_lines,
    log_path,
)

LOG_TAIL_LINES = 400


def register(app):
    @app.route("/logs")
    @login_required
    def logs():
        level = request.args.get("level") or ""
        # The bot and the panel write separate files, so which one you are
        # looking at is part of the page's state.
        name = live_log_name(request.args.get("file"))
        path = log_path(name)

        return render_template(
            "logs.html",
            lines=log_lines(LOG_TAIL_LINES, path, level=level or None),
            level=level,
            path=path,
            file=name,
            files=LIVE_LOG_NAMES,
            # Where the live tail should start reading from, so it appends
            # only what arrives after this render.
            offset=path.stat().st_size if path.exists() else 0,
            archives=log_files(),
        )

    @app.route("/logs/tail")
    @login_required
    def logs_tail():
        """New bytes since `offset`. Polled rather than streamed: a long-lived
        connection would tie up a worker and has to be re-established after
        every restart, for no gain at this size."""
        offset = request.args.get("offset", type=int, default=0)
        level = request.args.get("level") or None
        path = log_path(live_log_name(request.args.get("file")))

        if not path.exists():
            return jsonify(offset=0, lines=[])

        size = path.stat().st_size

        # Midnight rotation leaves the offset past the end of a fresh file.
        if offset > size:
            offset = 0

        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()

        # Stop at the last newline so a half-written line isn't shown, and so
        # the next poll doesn't start mid-character.
        cut = chunk.rfind(b"\n") + 1
        chunk, offset = chunk[:cut], offset + cut

        lines = chunk.decode("utf-8", errors="replace").splitlines()

        return jsonify(offset=offset, lines=at_level(lines, level))

    @app.route("/logs/download/<path:name>")
    @login_required
    def logs_download(name):
        # Only ever the files we listed ourselves — never a caller-supplied path.
        if name not in {entry["name"] for entry in log_files()}:
            abort(404)

        return send_from_directory(
            log_directory(), name, as_attachment=True, mimetype="text/plain",
        )
