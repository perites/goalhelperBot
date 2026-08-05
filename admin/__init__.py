"""Admin panel for Ксенія.

Runs as its own process rather than inside the bot: the bot is asyncio (PTB)
and Flask is WSGI, so sharing one process would mean threading one inside the
other for no benefit. Both open the same SQLite file, which WAL makes fine —
readers and one writer proceed at the same time.

It binds to localhost only and is reached through the same SSH tunnel as
sqlite-web (deploy/README-tunnel.md). Participants' answers are private, so
nothing about this is meant to be publicly routable — which is also why every
state-changing request carries a CSRF token: the tunnel puts the panel in the
same browser as everything else.
"""
