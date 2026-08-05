# Я хочу бот

A Telegram bot that walks one person through a personal 30-day cycle: a daily
question, their own intention repeated back to them, and a record of what they
noticed. Built for the coach Ксенія, for a pilot cohort of ten.

Two processes, one SQLite file:

- **the bot** (`main.py`) — polls Telegram, sends the questions, records the answers
- **the admin panel** (`admin_panel.py`) — a small web UI for Ксенія: participants, the question bank, the cohort, the
  logs, CSV export

---

## Layout

```
core/     what both of them need — the schema and the arithmetic on it, the
          domain vocabulary, the clock, settings, logging, and the services
          that answer questions about the data
bot/      Telegram: keyboards, message text, delivery, the hourly scheduler,
          and the handlers
admin/    Flask: routes, forms, sessions, log reading
samples/  a demo question bank, for a database that has nothing in it yet
tests/    the suite, and its own fixtures
deploy/   systemd units, backup, and how to reach the panel
```

**`core` may not import `telegram` or `flask`.** That is what lets the panel run
without a Telegram library in its process, and the bot without a web framework
in its. [`tests/test_layering.py`](tests/test_layering.py) checks it rather than
trusting anyone to remember.

---

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Create `.env` beside `main.py`:

```
BOT_TOKEN=...                  # from @BotFather
ADMIN_CHAT_IDS=123456789       # who gets alerts; comma-separated
ADMIN_PANEL_PASSWORD=...       # the panel's single password
ADMIN_SECRET_KEY=...           # signs sessions; see below
ADMIN_PANEL_PORT=8082          # optional
DATA_DIR=.                     # optional; where the database and logs go
LOG_LEVEL=INFO                 # optional
```

`ADMIN_SECRET_KEY` is required and the panel refuses to start without it —
sessions are signed with it, so an invented one means every restart logs you
out. Generate one:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Then:

```bash
python main.py
```

```bash
python admin_panel.py
```

The panel binds to `127.0.0.1` only.

A fresh database has no questions and no cohort, so the bot has nothing to send
and nobody can join. Either add them through the panel, or load the demo bank:

```bash
python -m samples.seed
```

---

## Tests

```bash
python -m pytest
```

No network, no wall clock, no `goalbot.db` — every test runs against a fresh
database and a frozen clock. The suite owns its own data in
`tests/factories.py`, so the demo content in `samples/` can be replaced with
real questions without a single assertion moving.

---

## Changing the schema

`create_tables(safe=True)` creates missing tables and nothing else — it cannot
add a column to a table that already exists. So from the first day of the pilot,
**every change to `core/models.py` needs a matching step in
[`core/migrations.py`](core/migrations.py)**, which explains how. How far a
database has got is in SQLite's own `user_version`:

```bash
sqlite3 goalbot.db 'PRAGMA user_version;'
```

---

## Data

Worth being able to answer plainly, since participants consented to it.

**What is stored, in `goalbot.db`:** a participant's Telegram id and username,
the name they gave, their intention and its category, the times they chose,
every answer they wrote and every question they skipped, and their closing
reflection. This is the point of the product — it is what the statistics screen
and the final summary are made from.

**Kept for:** as long as the database is. Nothing expires on its own. Ending
participation early keeps the answers, and the bot says so before it does it
(«Твої відповіді залишаться збереженими в будь-якому разі»).

**Logs** (`logs/bot.log`, `logs/admin.log`) hold Telegram ids, question ids and
counts — **never the text of an answer, an intention, or a name.** That is
enforced by using `describe()` in place of the content. They rotate at midnight
and 30 days are kept.

**`ptb_state.pickle`** holds the half-finished onboarding of anyone currently
partway through it, including the name and intention they have typed so far. It
is overwritten as they progress and cleared when they finish.

**Backups** contain all of the above — see
[deploy/backup.sh](deploy/backup.sh). They belong somewhere as private as the
server itself.

**There is no erasure path.** Deleting a participant means deleting their rows
by hand, and the foreign keys will make you do it in the right order (answers,
then times, then the user). If the pilot ever needs a supported "delete my
data", that is a feature to build rather than a script to run.
