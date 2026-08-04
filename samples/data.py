"""The starter question bank and the demo cohort's shape.

Placeholder content, kept out of the bot so that nothing in the running
application depends on it. Ксенія's real bank replaces this — either by
editing here and re-seeding an empty database, or through the admin panel.

Nothing in `bot/` or `admin/` imports this module.
"""
from bot.enums import QuestionType

# --- The demo cohort -------------------------------------------------------
#
# Every one of these is a Cohort column with no default of its own: a cohort
# states its own shape, and the bot reads it from there. These values decide
# the demo cohort only, and the admin panel edits it from then on.

ENROLLMENT_WINDOW_DAYS = 14
DURATION_DAYS = 30
MAX_PEOPLE = 10

# How many questions a participant receives per day, spread across whichever
# slots they chose. Timing is the participant's choice; volume is the
# programme's.
#
# Two things it is not:
#   - not a hard cap: every chosen slot is floored at one question, so picking
#     more slots than this number raises the daily total rather than leaving a
#     slot you asked for silent;
#   - not a guarantee: a slot's run only advances when a question is answered,
#     so going quiet ends the day early.
QUESTIONS_PER_DAY = 3

# The rhythm of the daily questions. Each send takes the next category here
# and picks a question of that type; after the last it wraps to the first, so
# the cycle runs continuously rather than restarting each day.
#
# A category may appear more than once to make it come round more often.
# Categories with no questions yet are skipped, so it's safe to list one
# before writing its questions.
#
# Note the interaction with QUESTIONS_PER_DAY: when the two lengths match,
# every day has the same shape (emotion, then a step, then gratitude). When
# they differ, the pattern rotates across days instead.
CATEGORY_ORDER = [
    QuestionType.EMOTION,
    QuestionType.STEP,
    QuestionType.GRATITUDE,
]

# Stored form: comma-joined QuestionType values.
CATEGORY_ORDER_CSV = ",".join(str(int(t)) for t in CATEGORY_ORDER)

# ТЗ §15's five closing questions — seed data for the FinalQuestion table.
final_questions = [
    "Що ти краще зрозуміла / зрозумів про свій намір?",
    "Що тобі вдалося зробити за ці 30 днів?",
    "Які емоції найчастіше супроводжували твій рух?",
    "Який маленький крок мав найбільше значення?",
    "Що ти хочеш продовжити після завершення цього циклу?",
]


intensity_options = ["1", "2", "3", "4", "5"]

# ТЗ §10.1's eleven emotions, grouped so the keyboard isn't a wall. A nested
# list is a group: the first item labels it, the rest are its choices. Only
# the chosen emotion is stored, never the group — the grouping is a way of
# fitting them on screen, not part of the answer.
emotion_options = [
    ["🌱 Радше приємні", "радість", "натхнення", "цікавість", "спокій"],
    ["🌧 Радше складні", "тривога", "злість", "сум", "втома", "розчарування"],
    "байдужість",
]

# Seed data for the question bank, until Ксенія provides the real one.
#
#   options      None for an open question; strings, or [label, choice, ...]
#                for a group of choices behind one button.
#   free_text    adds a "write your own" button beside the options.
#   follow_ups   asked one at a time once the parent is answered, and never
#                offered by the daily rotation.
sample_questions = [
    {
        "text": "Яку емоцію ти зараз відчуваєш стосовно свого наміру?",
        "type": QuestionType.EMOTION,
        "options": emotion_options,
        "free_text": False,
        "follow_ups": [
            {
                "text": "Наскільки сильно ти зараз це відчуваєш?",
                "type": QuestionType.EMOTION,
                "options": intensity_options,
            },
        ],
    },
    {
        "text": "Що ти сьогодні вже зробила / зробив для свого наміру, навіть якщо це був дуже маленький крок?",
        "type": QuestionType.STEP,
    },
    {
        "text": "Що зараз може стати для тебе точкою опори в русі до цього наміру?",
        "type": QuestionType.SUPPORT,
    },
    {
        "text": "За що ти сьогодні можеш себе цінувати в контексті свого наміру?",
        "type": QuestionType.GRATITUDE,
    },
    {
        "text": "Що зараз найбільше заважає тобі рухатися до цього наміру?",
        "type": QuestionType.OBSTACLE,
        # ТЗ §10.5 asks for exactly this follow-up.
        "follow_ups": [
            {
                "text": "Що з цього ти можеш зробити трохи простішим?",
                "type": QuestionType.OBSTACLE,
            },
        ],
    },
    {
        "text": "Яку маленьку перемогу ти можеш сьогодні помітити?",
        "type": QuestionType.WIN,
    },
    {
        "text": "Що сьогодні важливо не загубити, щоб залишатися в контакті зі своїм наміром?",
        "type": QuestionType.FOCUS,
    },
    {
        "text": "Який один маленький крок ти можеш зробити сьогодні?",
        "type": QuestionType.STEP,
    },
    {
        "text": "Яка емоція супроводжує тебе сьогодні найбільше?",
        "type": QuestionType.EMOTION,
        "options": emotion_options,
        "free_text": True,
        # ТЗ §10.1.
        "follow_ups": [
            {
                "text": "Що ця емоція може тобі підказувати?",
                "type": QuestionType.EMOTION,
            },
        ],
    },
    {
        "text": "Що сьогодні може допомогти тобі зробити хоча б один маленький крок у напрямку цього наміру?",
        "type": QuestionType.FOCUS,
    },
]
