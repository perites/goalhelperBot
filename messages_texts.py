from database import QuestionType

start_message = '''
Привіт. Я — “Я хочу бот”.
Я допоможу тобі протягом 30 днів тримати фокус на твоєму намірі, помічати свій стан, фіксувати маленькі кроки й бачити власний рух.

Це не про тиск і не про “треба”. Це про м’яке повернення до того, що для тебе важливо.
'''

start_message_button = '''🚀 Почати'''

onboarding_personal_data_message = '''
Щоб працювати з твоїми відповідями, бот буде зберігати твій намір, відповіді, обрані емоції та короткі записи протягом участі у 30-денному циклі.
Дані використовуються для твоєї особистої рефлексії та покращення продукту.
'''

onboarding_personal_data_message_yes = '''✅ Погоджуюсь'''
onboarding_personal_data_message_no = '''❌ Не погоджуюсь'''

onboarding_personal_data_declined_message = '''
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

onboarding_time_slots_message = '''
Коли тобі зручно отримувати повідомлення? Обери один або кілька варіантів.
'''

onboarding_time_slots_continue_button = '''Продовжити ➡️'''

onboarding_time_slots_empty_warning = '''
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

onboarding_first_question_placeholder = '''
День 1 із 30.
Це буде твоє перше питання дня 🙂
'''

menu_my_info_button = '''📝 Моя інформація'''
menu_contacts_button = '''💬 Контакти Ксенії'''
menu_stats_button = '''📊 Моя статистика'''
menu_edit_times_button = '''⏰ Змінити час повідомлень'''
menu_finish_button = '''🚪 Завершити участь'''

main_menu_buttons = [
    menu_my_info_button,
    menu_contacts_button,
    menu_stats_button,
    menu_edit_times_button,
    menu_finish_button,
]

menu_edit_times_message = '''
Коли тобі зручно отримувати повідомлення? Обери один або кілька варіантів.
'''

menu_edit_times_save_button = '''Зберегти ✅'''

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

menu_contacts_message = '''
Зв'язатися зі мною:

Telegram: @kryskaks

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

Твої відповіді залишаться збереженими. Питання більше не приходитимуть.
'''

menu_finish_confirm_yes_button = '''Так, завершити'''
menu_finish_confirm_no_button = '''Ні, продовжую'''

menu_finish_confirmed_message = '''
Добре. Твоя участь завершена.

Дякую за час, який ти приділила / приділив собі в ці дні.
Якщо захочеш повернутися — просто напиши /start.
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

question_answer_prompt = '''
Напиши свою відповідь одним повідомленням.
'''

question_saved_message = '''
Дякую, я зберіг твою відповідь.
'''

question_skipped_message = '''
Добре, пропускаємо це питання.
Не потрібно нічого надолужувати — достатньо помітити.
'''

question_already_closed_message = '''
Це питання вже закрите. Наступне прийде у свій час.
'''

emotion_options = [
    "радість",
    "натхнення",
    "цікавість",
    "спокій",
    "тривога",
    "злість",
    "сум",
    "втома",
    "розчарування",
    "байдужість",
    "інше",
]

# (text, type, options) — options is None for an open question.
# Placeholder set until Ксенія provides the real question bank.
sample_questions = [
    (
        "Яку емоцію ти зараз відчуваєш стосовно свого наміру?",
        QuestionType.EMOTION,
        emotion_options,
    ),
    (
        "Що ти сьогодні вже зробила / зробив для свого наміру, навіть якщо це був дуже маленький крок?",
        QuestionType.STEP,
        None,
    ),
    (
        "Що зараз може стати для тебе точкою опори в русі до цього наміру?",
        QuestionType.SUPPORT,
        None,
    ),
    (
        "За що ти сьогодні можеш себе цінувати в контексті свого наміру?",
        QuestionType.GRATITUDE,
        None,
    ),
    (
        "Що зараз найбільше заважає тобі рухатися до цього наміру?",
        QuestionType.OBSTACLE,
        None,
    ),
    (
        "Яку маленьку перемогу ти можеш сьогодні помітити?",
        QuestionType.WIN,
        None,
    ),
    (
        "Що сьогодні важливо не загубити, щоб залишатися в контакті зі своїм наміром?",
        QuestionType.FOCUS,
        None,
    ),
    (
        "Який один маленький крок ти можеш зробити сьогодні?",
        QuestionType.STEP,
        None,
    ),
    (
        "Яка емоція супроводжує тебе сьогодні найбільше?",
        QuestionType.EMOTION,
        emotion_options,
    ),
    (
        "Що сьогодні може допомогти тобі зробити хоча б один маленький крок у напрямку цього наміру?",
        QuestionType.FOCUS,
        None,
    ),
]
