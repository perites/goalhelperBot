from app.config import KSENIA_TELEGRAM
from app.enums import QuestionType

start_message = '''
Привіт. Я — “Я хочу бот”.
Я допоможу тобі протягом 30 днів тримати фокус на твоєму намірі, помічати свій стан, фіксувати маленькі кроки й бачити власний рух.

Це не про тиск і не про “треба”. Це про м’яке повернення до того, що для тебе важливо.
'''

start_message_button = '''🚀 Почати'''

consent_message = '''
Щоб працювати з твоїми відповідями, бот буде зберігати твій намір, відповіді, обрані емоції та короткі записи протягом участі у 30-денному циклі.
Дані використовуються для твоєї особистої рефлексії та покращення продукту.
'''

consent_yes_button = '''✅ Погоджуюсь'''
consent_no_button = '''❌ Не погоджуюсь'''

consent_declined_message = '''
Добре, розумію.
Без згоди на обробку даних бот не може розпочати участь.
Якщо передумаєш — просто напиши /start ще раз.
'''

onboarding_name_message = '''
Як до тебе звертатися?
'''

onboarding_category_message = '''
З чого починається твоє “Я хочу”?
'''

category_labels = [
    "Почати",
    "Завершити",
    "Навчитися",
    "Побудувати звичку",
    "Отримати результат",
    "Стати більш / більшою",
    "Відпустити / перестати",
    "Розібратися",
    "Інше",
]

onboarding_intention_message = '''
Сформулюй своє “Я хочу” одним реченням.
Наприклад: “Я хочу почати регулярно писати в LinkedIn” або “Я хочу побудувати звичку щоденної рефлексії”.
Ти вибрав: “Я хочу {intention_type}...“
'''

slots_prompt_message = '''
Коли тобі зручно отримувати повідомлення? Обери один або кілька варіантів.
'''

slots_continue_button = '''Продовжити ➡️'''

slots_empty_warning = '''
Обери хоча б один час.
'''

onboarding_confirm_template = '''
Твій намір на ці 30 днів:
“{intention}”

Ім'я: {name}
Категорія: {category}
Час повідомлень: {times}

Чи залишаємо так?
'''

onboarding_confirm_yes_button = '''✅ Так, залишаємо'''

onboarding_confirm_restart_button = '''✏️ Хочу змінити'''

onboarding_confirmed_message = '''
Домовились.
Твій 30-денний цикл починається.
Я буду повертати тебе до твого наміру, ставити питання й допомагати помічати маленькі кроки.
'''

onboarding_ready_message = '''
Почнемо з першого питання?
'''

onboarding_ready_button = '''Так, почати'''

onboarding_menu_ready_message = '''
Меню завжди під рукою — там можна подивитися свій намір, статистику, змінити час повідомлень або зробити паузу.

А ось і перше питання 👇
'''

menu_my_info_button = '''📝 Моя інформація'''
menu_contacts_button = '''💬 Контакти Ксенії'''
menu_stats_button = '''📊 Моя статистика'''
menu_edit_times_button = '''⏰ Змінити час повідомлень'''
menu_pause_button = '''⏸ Зробити паузу'''
menu_finish_button = '''🚪 Завершити участь'''

main_menu_buttons = [
    menu_my_info_button,
    menu_contacts_button,
    menu_stats_button,
    menu_edit_times_button,
    menu_pause_button,
    menu_finish_button,
]

menu_not_participant_message = '''
Здається, ти ще не почала / почав свій 30-денний цикл.

Напиши /start, щоб приєднатися.
'''

menu_pause_confirm_message = '''
Хочеш зробити паузу на 3 дні?

Ці дні не зарахуються у твій цикл — я просто зачекаю, а потім ми продовжимо з того місця, де зупинились.
Повернутися раніше можна будь-коли.
'''

menu_pause_confirm_yes_button = '''Так, зробити паузу'''
menu_pause_confirm_no_button = '''Ні, продовжую'''

menu_paused_message = '''
Добре. Я зачекаю.

Питання не приходитимуть найближчі 3 дні. Якщо захочеш повернутися раніше — просто натисни “Продовжити”.
'''

menu_pause_cancelled_message = '''
Добре, продовжуємо.
'''

menu_already_paused_template = '''
Ти зараз на паузі. Залишилось днів: {days_left}

Ці дні не зараховуються у твій цикл.
'''

menu_resume_button = '''▶️ Продовжити'''

menu_resumed_message = '''
З поверненням.
Продовжуємо з того місця, де зупинились.
'''

slots_save_button = '''Зберегти ✅'''

menu_edit_times_saved_template = '''
Готово. Тепер я писатиму тобі: {times}
'''

menu_my_info_template = '''
Твій намір на ці 30 днів:
“{intention}”

Ім'я: {name}
Категорія: {category}
Час повідомлень: {times}
День циклу: {day} із {total}
'''

menu_contacts_message = f'''
Зв'язатися зі мною:

Telegram: {KSENIA_TELEGRAM}

Напиши, якщо виникають питання, хочеться щось прояснити або просто поділитися тим, що відбувається.
Там само можна домовитися про зустріч — ознайомчу або підсумкову рефлексійну, коли завершиш свій цикл.
'''

menu_stats_template = '''
Твоя статистика за {day} днів:

Відповідей: {answered}
Пропущено: {skipped}
Найчастіші емоції: {emotions}
Зафіксовано кроків: {steps}
Маленьких перемог: {wins}
Моментів вдячності: {gratitude}
'''

menu_stats_no_emotions = '''поки що немає'''

menu_finish_confirm_message = '''
Хочеш завершити участь у 30-денному циклі?

Це рішення остаточне — повернутися до цього циклу вже не вийде.

Якщо просто потрібна перерва, можна натомість зробити паузу на 3 дні: ці дні не зарахуються, і ми продовжимо з того самого місця.

Твої відповіді залишаться збереженими в будь-якому разі.
'''

menu_finish_confirm_yes_button = '''Так, завершити'''
menu_finish_confirm_no_button = '''Ні, продовжую'''

menu_finish_confirmed_message = '''
Добре. Твоя участь завершена.

Дякую за час, який ти приділила / приділив собі в ці дні.
Твої відповіді збережені — вони залишаються твоїми.
'''

cohort_waitlist_full_message = f'''
Дякую за інтерес до “Я хочу бота”.

У цьому пілотному запуску вже зайняті всі місця.

Я зберегла твій контакт — і напишу тобі, щойно відкриється наступний набір.
Якщо хочеться поговорити раніше, можна написати мені напряму: {KSENIA_TELEGRAM}
'''

cohort_waitlist_closed_message = f'''
Пілотний набір у “Я хочу бот” вже закритий.
Зараз учасники проходять свій 30-денний цикл.

Я зберегла твій контакт — і напишу тобі, щойно відкриється наступний набір.
Якщо хочеться поговорити раніше, можна написати мені напряму: {KSENIA_TELEGRAM}
'''

cohort_waitlist_not_open_message = f'''
Дякую за інтерес до “Я хочу бота”.

Набір ще не відкрився.

Я зберегла твій контакт — і напишу тобі, щойно можна буде доєднатися.
Якщо хочеться поговорити раніше, можна написати мені напряму: {KSENIA_TELEGRAM}
'''

cohort_already_stopped_message = f'''
Ти вже завершила / завершив участь у цьому циклі, тож повернутися до нього не вийде.

Якщо захочеш приєднатися до наступного запуску — напиши мені, і я додам тебе до списку: {KSENIA_TELEGRAM}
'''

cohort_finished_message = '''
Ти вже пройшла / пройшов свої 30 днів у цьому циклі.

Дякую, що була / був у цьому процесі.
'''

cycle_final_intro = '''
Це {total}-й день твого циклу з “Я хочу ботом”.

Запрошую тебе подивитися на цей період як на дослідження: що змінилося, що стало видимим, що хочеться забрати з собою далі.

Ось кілька останніх питань. Можеш відповісти на них одним повідомленням — так, як тобі зручно, і тоді, коли буде час.
'''

# ТЗ §15's five closing questions — seed data for the FinalQuestion table.
final_questions = [
    "Що ти краще зрозуміла / зрозумів про свій намір?",
    "Що тобі вдалося зробити за ці 30 днів?",
    "Які емоції найчастіше супроводжували твій рух?",
    "Який маленький крок мав найбільше значення?",
    "Що ти хочеш продовжити після завершення цього циклу?",
]


def final_questions_block(total, questions):
    numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(questions, start=1))

    return f"{cycle_final_intro.format(total=total).strip()}\n\n{numbered}"


cycle_final_summary_intro = '''
Дякую за твої відповіді.

Ось як виглядав твій шлях за ці {total} днів:
'''

cycle_final_invite_message = f'''
У межах першого тестового запуску ти можеш записатися на підсумкову рефлексійну зустріч.

На зустрічі ми подивимось на твій досвід, твої відповіді, кроки, емоції й те, що стало видимим за ці дні.

Написати мені: {KSENIA_TELEGRAM}

Дякую, що була / був у цьому процесі.
'''

menu_finish_cancelled_message = '''
Добре, продовжуємо.
'''

question_message_template = '''
День {day} із {total}.
Твій намір: “{intention}”

Питання дня:
{question}
'''

question_answer_button = '''Відповісти'''

question_skip_button = '''Пропустити це питання'''

question_back_button = '''⬅️ Повернутись'''

question_free_text_button = '''✏️ Інше (написати самому)'''

question_answer_prompt = '''
Напиши свою відповідь одним повідомленням.
'''

question_saved_message = '''
Дякую, я зберіг твою відповідь.
'''

# Appended to the original question message once it's resolved, so the chat
# history reads as a record rather than a list of orphaned prompts.
question_answered_suffix = '''

✏️ Твоя відповідь:
{answer}'''

question_skipped_suffix = '''

⏭ Пропущено'''

question_skipped_message = '''
Добре, пропускаємо це питання.
Не потрібно нічого надолужувати — достатньо помітити.
'''

question_already_closed_message = '''
Це питання вже закрите. Наступне прийде у свій час.
'''

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
