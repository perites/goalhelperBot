"""Reading what a form posted.

The templates mark their inputs `required` and `type=number`, but that is the
browser's opinion and only the browser's: a stale tab, a resubmitted form, or
anything that is not a browser posts whatever it likes. These read each field
once and say what was wrong, so a bad value is a message rather than a 500 —
and so nothing out of range reaches a column that another page later reads back
and chokes on.
"""
import json
from datetime import datetime

from core.enums import QuestionType
from core.models import Question
from core.settings import QUESTION_ORDER_STEP


class FormError(ValueError):
    """A submitted field the panel could not make sense of.

    The message is shown to the admin as-is, so it names the field and says
    what was expected. Raised rather than returned so a whole form can be read
    as one expression, with the first problem stopping it.
    """


def parse_options(raw):
    """The options field is JSON. Blank means an open question."""
    raw = (raw or "").strip()
    if not raw:
        return None

    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("options must be a JSON list")

    return json.dumps(parsed, ensure_ascii=False)


def text_field(form, name, label):
    value = (form.get(name) or "").strip()
    if not value:
        raise FormError(f"«{label}»: не може бути порожнім.")

    return value


def int_field(form, name, label, minimum=1):
    raw = (form.get(name) or "").strip()

    try:
        value = int(raw)
    except ValueError:
        raise FormError(f"«{label}»: очікується число, а не «{raw}».")

    if value < minimum:
        raise FormError(f"«{label}»: не може бути менше {minimum}.")

    return value


def date_field(form, name, label):
    raw = (form.get(name) or "").strip()

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise FormError(
            f"«{label}»: очікується дата у форматі РРРР-ММ-ДД, а не «{raw}»."
        )


def enum_field(form, name, label, enum, allowed=None):
    """One `int()` and one lookup, so a value that is not a number and a number
    that is not a member fail the same way.

    `allowed` narrows it further, for a field where some members exist but are
    not the form's to set — the posted value is checked here rather than only
    hidden from the select, since the select is not what enforces it.
    """
    raw = (form.get(name) or "").strip()

    try:
        value = enum(int(raw))
    except ValueError:
        raise FormError(f"«{label}»: невідоме значення «{raw}».")

    if allowed is not None and value not in allowed:
        raise FormError(f"«{label}»: значення «{value.name}» не встановлюють вручну.")

    return value


def category_order_field(form, name="category_order"):
    """The rhythm as the builder posts it: QuestionType values joined by commas.

    Empty is allowed and means "not decided yet" — the cohort page says plainly
    what that costs, and refusing to save would trap a half-built cohort.
    """
    raw = (form.get(name) or "").strip()
    if not raw:
        return ""

    known = {member.value for member in QuestionType}

    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) not in known:
            raise FormError(f"«Порядок категорій»: невідома категорія «{part}».")

    return raw


def parent_field(form, question):
    """Which rotation question this one is a follow-up to, or None.

    The dropdown only ever offers rotation questions, but nothing stopped a
    POST naming something else — and a question parented to itself, or hung off
    another follow-up, leaves the rotation without any way back.
    """
    raw = (form.get("parent") or "").strip()
    if not raw:
        return None

    try:
        parent_id = int(raw)
    except ValueError:
        raise FormError(f"«Уточнення до»: невідоме питання «{raw}».")

    parent = Question.get_or_none(Question.id == parent_id)
    if parent is None:
        raise FormError("«Уточнення до»: такого питання вже немає.")

    if question is not None and parent.id == question.id:
        raise FormError("«Уточнення до»: питання не може уточнювати саме себе.")

    if parent.parent_id is not None:
        raise FormError("«Уточнення до»: уточнення до уточнення не підтримуються.")

    return parent.id


def next_order(model):
    """The next `order` value for a bank, leaving a gap so a question can be
    slotted in between two others later without renumbering."""
    highest = model.select(model.order).order_by(model.order.desc()).first()

    return (highest.order + QUESTION_ORDER_STEP) if highest else QUESTION_ORDER_STEP
