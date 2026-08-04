"""Everything the Telegram bot and the admin panel both need.

The rule that keeps this package honest: **nothing here may import `telegram`
or `flask`.** They are two front ends onto one set of rules, and a rule that
knows what an inline keyboard is has stopped being a rule. `tests/test_layering.py`
checks it rather than trusting anyone to remember.

What lives here: the schema and the cycle arithmetic on it, the domain
vocabulary, the clock, the settings both processes read, logging, and the
services that answer questions about the data — who is enrolled, whose cycle
has ended, which question comes next, what may be deleted.

What does not: sending anything, drawing anything, and any word of Ukrainian
that a participant will read. Those belong to whichever front end is speaking.
"""
