"""Admin panel for Ксенія.

Runs as its own process rather than inside the bot: the bot is asyncio (PTB)
and Flask is WSGI, so sharing one process would mean threading one inside the
other for no benefit. Both open the same SQLite file, which is fine — reads
are concurrent and writes here are rare.

It binds to localhost only and is reached through the same SSH tunnel as
sqlite-web. Participants' answers are private, so nothing about this is meant
to be publicly routable.
"""
