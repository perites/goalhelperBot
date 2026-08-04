"""What may be permanently deleted, and what may not.

Deleting is the exception in this project. Anything a participant has already
seen stays on record — the admin withdraws it with «Зняти з ротації» instead,
so the wording of what was actually asked survives next to the answers. These
rules exist for the other case: the question added with a typo five minutes
ago, the cohort created by mistake. Rows with no history behind them.

Each `*_blocker` returns the reason a row cannot go, or None when it can. The
panel calls them to grey out its buttons, but that is a courtesy — the
`delete_*` functions re-run the same check inside the deleting transaction, so
a hand-made POST hits the identical guard.
"""
from bot.enums import Status
from bot.logs import get_logger
from bot.models import Answer, FinalAnswer, User, db

logger = get_logger(__name__)


class DeletionBlocked(Exception):
    """A delete was attempted on a row that has history behind it. The message
    is the same one the panel shows, so a caller can surface it directly."""


def question_blocker(question):
    """A daily question or follow-up is deletable until it has been sent.

    One check covers both halves of the rule: the Answer row is created at send
    time, so its presence means the question is either sitting in someone's
    chat awaiting a reply or has already been answered."""
    follow_ups = question.follow_ups.count()
    if follow_ups:
        # Nothing cascades here, so deleting a parent would leave its children
        # pointing at a row that no longer exists.
        return (
            f"Спершу приберіть уточнення ({follow_ups}) — "
            f"видаліть їх або прикріпіть до іншого питання."
        )

    sent = Answer.select().where(Answer.question == question).count()
    if sent:
        answered = (
            Answer.select()
            .where((Answer.question == question) & Answer.answered_at.is_null(False))
            .count()
        )
        waiting = (
            Answer.select()
            .where(
                (Answer.question == question)
                & Answer.answered_at.is_null(True)
                & (Answer.skipped == False)  # noqa: E712 - peewee needs the comparison
            )
            .count()
        )

        detail = f"надсилалося {sent} раз(ів)"
        if answered:
            detail += f", відповідей: {answered}"
        if waiting:
            detail += f", очікує на відповідь: {waiting}"

        return f"Питання вже в роботі ({detail}). Зніміть його з ротації."

    return None


def final_question_blocker(question):
    """A closing question is deletable until it has gone out inside a block.

    FinalAnswer holds no reference to individual questions — the whole block is
    one message — but it stores the exact text that was sent, and closing
    questions cannot be reworded after the fact. So the sent text is the record
    of which questions took part."""
    for sent in FinalAnswer.select(FinalAnswer.message_text):
        if sent.message_text is None:
            # Shouldn't happen: send_closing_block always stores the body. If
            # it ever does, we cannot tell what was asked, so nothing goes.
            return "Не вдається перевірити: у надісланого блоку не збережено тексту."

        if question.text in sent.message_text:
            return "Питання вже надсилалося учасникам у підсумковому блоці. Зніміть його."

    return None


def cohort_blocker(cohort):
    """A cohort is deletable while nothing hangs off it.

    Participants are the only rows that reference a cohort, and they in turn
    own the answers and the schedule — so no participants means no dependent
    data anywhere."""
    participants = User.select().where(User.cohort == cohort).count()
    if participants:
        seated = (
            User.select()
            .where((User.cohort == cohort) & (User.status != Status.ONBOARDING))
            .count()
        )

        detail = f"учасників: {participants}"
        if seated:
            detail += f", з них уже проходять або пройшли: {seated}"

        return f"У когорті є люди ({detail}) разом з їхніми відповідями."

    if cohort.is_active:
        return "Когорта активна — саме в неї потрапляють нові учасники. Спершу активуйте іншу."

    return None


def delete_question(question):
    """Delete a daily question for good, or raise DeletionBlocked."""
    with db.atomic("IMMEDIATE"):
        blocker = question_blocker(question)
        if blocker:
            raise DeletionBlocked(blocker)

        question.delete_instance()

    logger.warning("Question id=%s deleted from the admin panel", question.id)


def delete_final_question(question):
    """Delete a closing question for good, or raise DeletionBlocked."""
    with db.atomic("IMMEDIATE"):
        blocker = final_question_blocker(question)
        if blocker:
            raise DeletionBlocked(blocker)

        question.delete_instance()

    logger.warning("Final question id=%s deleted from the admin panel", question.id)


def delete_cohort(cohort):
    """Delete a cohort for good, or raise DeletionBlocked."""
    with db.atomic("IMMEDIATE"):
        blocker = cohort_blocker(cohort)
        if blocker:
            raise DeletionBlocked(blocker)

        cohort.delete_instance()

    logger.warning("Cohort id=%s (%s) deleted from the admin panel", cohort.id, cohort.name)
