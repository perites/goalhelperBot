"""The callback-data protocol.

Telegram gives an inline button 64 bytes of opaque data and hands that string
straight back when it is tapped. Everything a handler needs to know about a tap
has to fit in it, and every handler has to agree on the shape — which used to
mean `query.data.split(":")` in six places with three different arities, and
prefixes declared half in config and half inline.

One module decides it now. Adding a field is one edit, the patterns handlers
register with are built from the same constants the buttons are, and data that
does not parse is rejected here rather than raising somewhere inside a handler.

The shape is `action:part:part`, and the separator is a colon because slot ids
already contained one before any of this was written — see `payload`.
"""

SEPARATOR = ":"

# --- Actions ---------------------------------------------------------------
#
# A tap either resolves a question, moves through onboarding, or works one of
# the menu's confirmations. Values are what actually travels to Telegram and
# back, so shortening one abandons every button already sitting in a chat.

ANSWER = "answer"
SKIP = "skip"
OPTION = "option"
GROUP = "group"

START_ONBOARDING = "start"
CONSENT = "consent"
CATEGORY = "category"
CONFIRM = "confirm"
READY = "ready"

PAUSE = "pause"
FINISH = "finish"

TIME_SLOT = "time_slot"
EDIT_TIME = "edit_time"

# --- Well-known parts ------------------------------------------------------

# Returns from a group of options to the top level of a question's keyboard.
BACK = "back"

# Confirms a slot picker, whichever of the two it is.
CONTINUE = "continue"

YES = "yes"
NO = "no"
RESUME = "resume"
RESTART = "restart"

# What the button on the /start message begins.
ONBOARDING = "onboarding"


def encode(action, *parts):
    """Callback data for a button."""
    return SEPARATOR.join([action, *(str(part) for part in parts)])


def parts(data):
    """Everything after the action, split.

    Not for values that contain a separator themselves — see `payload`.
    """
    return data.split(SEPARATOR)[1:]


def payload(data):
    """Everything after the action, unsplit.

    A slot is identified by its own time, so its id contains the separator:
    "edit_time:09:00" carries one value, not two.
    """
    return data.partition(SEPARATOR)[2]


def indexes(data):
    """The parts as a list of non-negative integers, or None.

    Every button carrying these is one we drew, so this should always succeed.
    It comes back from the client though, and a chat can hand back anything it
    still has on screen — including, before this existed, a negative index that
    would quietly resolve to an option counted from the other end.
    """
    try:
        values = [int(part) for part in parts(data)]
    except ValueError:
        return None

    return values if all(value >= 0 for value in values) else None


def pattern(action):
    """Matches any tap of this action — for `CallbackQueryHandler(pattern=...)`."""
    return f"^{action}{SEPARATOR}"


def exact(action, *parts_):
    """Matches one specific tap and nothing else.

    Needed where one action's pattern is a prefix of another's: the slot
    pickers' "save" must be matched before their "toggle", which would
    otherwise swallow it.
    """
    return f"^{encode(action, *parts_)}$"
