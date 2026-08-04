"""Domain errors.

Kept out of the services so models and services can both raise them without
importing each other.
"""


class CohortMissing(Exception):
    """A participant's cycle settings were needed, but they are in no cohort.

    Cycle length, the daily question total, and the category rhythm are all
    properties of a cohort — there is no answer to "how long is their cycle"
    for someone outside one. Rather than substitute a guess, this is raised so
    the caller can skip that participant and say so in the log.

    It should never fire in practice: joining a cohort is what makes someone
    ACTIVE, and every query that drives the cycle filters on having one. If it
    does fire, a participant is in a state the bot has no rules for.
    """

    def __init__(self, user, needed):
        super().__init__(
            f"user={getattr(user, 'telegram_id', user)} is in no cohort, "
            f"so {needed} is undefined"
        )
        self.user = user
        self.needed = needed
