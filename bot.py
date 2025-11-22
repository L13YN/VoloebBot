import asyncio
import logging
import re
import os
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram import ReplyKeyboardMarkup
from flask import Flask
from threading import Thread
import requests
import time

# ========== НАСТРОЙКИ ДЛЯ RAILWAY ==========
BOT_TOKEN = os.environ['BOT_TOKEN']  # Обязательно через переменные окружения!
GROUP_ID = -1003401230283
TOPIC_ID = 4
SPORT_TOPIC_ID = 6
MONTHLY_TOPIC_ID = 130

# Кодовые слова для отслеживания
KEYWORD = "Выполнил все задачи на сегодня"
SPORT_KEYWORD = "Выполнил все спортивные задачи на сегодня"
PROGRESS_KEYWORD = "Промежуточный итог"
SPORT_PROGRESS_KEYWORD = "Спортивный промежуточный итог"
CHECK_INTERVAL = 3600  # 1 час
PROGRESS_CHECK_INTERVAL = 5400  # 1.5 часа

# Время начала напоминаний (10 утра по Екатеринбургу UTC+5)
START_HOUR = 10
TIMEZONE_OFFSET = 5

# ========== FLASK APP ДЛЯ HEALTH CHECKS ==========
app = Flask(__name__)


@app.route('/')
def home():
    return "🤖 Бот активен и работает на Railway 24/7!"


@app.route('/health')
def health():
    return "OK"


@app.route('/ping')
def ping():
    return "pong"


def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


def keep_alive():
    """Запускает Flask сервер в отдельном потоке"""
    server = Thread(target=run_flask, daemon=True)
    server.start()


# ========== ХРАНИЛИЩЕ ДАННЫХ ==========
user_keyword_dates = {}
user_sport_keyword_dates = {}
user_progress = {}
user_sport_progress = {}
user_monthly_goals = {}
subscribed_users = set()

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ========== АГРЕССИВНЫЕ СООБЩЕНИЯ ==========
MORNING_REMINDERS = [
    "Уебище, проснись и пошевеливайся! Где твой ебучий список дел на день? Я не намерен тут в прокрастинации тонуть!\n\n👇 Напиши в соответствующих темах:\n• В теме IT - список IT задач\n• В теме Спорт - спортивный план\n• В теме месячных целей - цели на месяц\n\nФормат:\n1. Задача 1\n2. Задача 2\n3. Задача 3",
    "Ты че, спать до обеда собрался, мудила? Поднимай свою жопу и составляй список дел! Я не шутка хуйня какая-то!\n\n👇 Напиши в соответствующих темах:\n• В теме IT - список IT задач\n• В теме Спорт - спортивный план\n• В теме месячных целей - цели на месяц\n\nФормат:\n1. Задача 1\n2. Задача 2\n3. Задача 3",
    "А ну-ка, прекращай сидеть на толчке и займись делом, уебок! Где твои ебучие задачи на сегодня?\n\n👇 Напиши в соответствующих темах:\n• В теме IT - список IT задач\n• В теме Спорт - спортивный план\n• В теме месячных целей - цели на месяц\n\nФормат:\n1. Задача 1\n2. Задача 2\n3. Задача 3"
]

COMPLETED_IT_TASKS = [
    "Этот хуесос выполнил все свои IT задачи на сегодня! Я в ахуе, но завтра опять нажремся работы, мудила!",
    "Бля, этот долбоеб реально сделал все IT задачи! Может он не такой уж и еблан? Хотя нет, завтра опять будете страдать, уебаны!",
    "Охуеть! Этот мудак завершил все IT задачи! Но не расслабляйся, завтра тебя ждет новый пиздец!"
]

COMPLETED_SPORT_TASKS = [
    "Этот дрищ выполнил всю свою фитнес программу на сегодня, я в ахуе. Но завтра опять будешь страдать, мудила!",
    "Бля, этот хуила сделал все спортивные упражнения! Может ты не такой уж и слабак? Хотя нет, завтра опять будешь еле ноги таскать!",
    "Охуеть! Этот мудак не сдох на тренировке! Все спортивные задачи выполнены, но завтра опять будет пиздец!"
]

PROGRESS_RESPONSES_IT = [
    "Ну наконец-то, этот хуесос сделал {completed} из {total} IT задач! Осталось еще {remaining}, не расслабляйся, мудила! 💪",
    "Бля, {completed} задач из {total} готово? Неплохо для такого уебища! Осталось {remaining} - давай, сука, работай! 🖥️",
    "Охуеть, {completed} IT задач сделано! Осталось всего {remaining} из {total}, не пизди что устал! 💻"
]

PROGRESS_RESPONSES_SPORT = [
    "Этот дрищ сделал {completed} из {total} упражнений! Осталось {remaining} - не сдавайся, мудила! 🏃‍♂️",
    "Бля, {completed} упражнений из {total}? Неплохо для слабака! Осталось {remaining} - давай, сука, жги! 💪",
    "Охуеть, {completed} спортивных задач готово! Осталось {remaining} из {total}, не ной что тяжело! 🏋️"
]

REMINDERS_NO_TASKS = [
    "Ты че, долбоеб, до сих пор не написал список задач? Или ты думаешь я тут для красоты? Пиши быстро, уебок!",
    "Блядь, где твои ебучие задачи? Ты думаешь они сами появятся? Не будь мудаком, напиши уже!",
    "А ну-ка, прекрати срать и займись делом! Где твой список задач, уебище?"
]

REMINDERS_WITH_TASKS = [
    "Ты че, долбоеб, еще не отчитался о выполнении? {total} задач висят, а ты тут хуйней страдаешь! Отчитывайся быстро!",
    "Блядь, {total} задач ждут твоего отчета! Ты думаешь они сами сделаются? Не будь мудаком, пиши прогресс!",
    "А ну-ка, прекрати проебывать время! {total} задач требуют отчета, сука! Шевелись!"
]

PROGRESS_REMINDERS = [
    "Ты че, остановился, мудила? Осталось {remaining} из {total} задач! Не расслабляйся, уебок!",
    "Блядь, всего {remaining} из {total} осталось! Ты думаешь это повод расслабиться? Вперед, сука!",
    "А ну-ка, не сдавайся, хуесос! Осталось {remaining} из {total} - давай, работай!"
]

DAILY_RESET_MESSAGES = [
    "🔄 Наступил новый день, уебаны! Время снова страдать!\n\nНе забудьте:\n1. Написать в теме IT ваш список задач\n2. Написать в теме Спорт ваш спортивный план\n3. Отчитываться о прогрессе как мужики!\n\nФормат отчетов:\n• 'Промежуточный итог: выполнил N задач' - для IT\n• 'Спортивный промежуточный итог: выполнил N упражнений' - для спорта",
    "🔄 Блядь, опять новый день! Готовьтесь к новому пиздецу!\n\nЧто делать:\n1. IT задачи в соответствующей теме\n2. Спортивный план в теме Спорт\n3. Отчитываться как не мудаки\n\nКак отчитываться:\n• 'Промежуточный итог: выполнил N задач' - IT\n• 'Спортивный промежуточный итог: выполнил N упражнений' - спорт",
    "🔄 Охуеть, уже новый день! Время снова ебать мозги!\n\nНе проебывайте:\n1. Список IT задач\n2. Спортивный план\n3. Отчеты о прогрессе\n\nДля отчетов:\n• 'Промежуточный итог: выполнил N задач' - IT\n• 'Спортивный промежуточный итог: выполнил N упражнений' - спорт"
]


# ========== СУЩЕСТВУЮЩИЕ ФУНКЦИИ ==========
def get_ekaterinburg_time():
    """Получает текущее время в Екатеринбурге (UTC+5)"""
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)


def should_send_reminders():
    """Проверяет, можно ли отправлять напоминания (после 10 утра по Екатеринбургу)"""
    current_time = get_ekaterinburg_time()
    return current_time.hour >= START_HOUR


def parse_tasks_from_message(message_text):
    """Парсит список задач из сообщения пользователя"""
    tasks = []
    lines = message_text.split('\n')

    for line in lines:
        match = re.match(r'^(\d+)[\.\)]\s*(.+)$', line.strip())
        if match:
            task_number = int(match.group(1))
            task_text = match.group(2).strip()
            tasks.append((task_number, task_text))

    return tasks


def parse_monthly_goals(message_text):
    """Парсит месячные цели из сообщения пользователя"""
    goals = []
    lines = message_text.split('\n')

    found_header = False
    for line in lines:
        if re.search(r'цели\s+на\s+месяц', line.lower()):
            found_header = True
            continue

        if found_header:
            match = re.match(r'^(\d+)[\.\)]\s*(.+)$', line.strip())
            if match:
                goal_number = int(match.group(1))
                goal_text = match.group(2).strip()
                goals.append((goal_number, goal_text))

    if not goals:
        for line in lines:
            match = re.match(r'^(\d+)[\.\)]\s*(.+)$', line.strip())
            if match:
                goal_number = int(match.group(1))
                goal_text = match.group(2).strip()
                goals.append((goal_number, goal_text))

    return goals


def get_total_tasks_from_list(tasks_list):
    """Определяет общее количество задач из списка (максимальный номер)"""
    if not tasks_list:
        return 0
    return max(task[0] for task in tasks_list)


def count_users_written_today():
    """Считает сколько пользователей написали IT кодовое слово сегодня"""
    today = datetime.now().date()
    count = 0
    for user_id, last_date in user_keyword_dates.items():
        if last_date == today:
            count += 1
    return count


def count_sport_users_written_today():
    """Считает сколько пользователей написали спортивное кодовое слово сегодня"""
    today = datetime.now().date()
    count = 0
    for user_id, last_date in user_sport_keyword_dates.items():
        if last_date == today:
            count += 1
    return count


# ========== ИСПРАВЛЕННАЯ ФУНКЦИЯ: УТРЕННЕЕ НАПОМИНАНИЕ ==========
async def send_morning_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет утреннее напоминание в 10 утра по Екатеринбургу только тем, кто еще не написал цели"""
    try:
        current_time = get_ekaterinburg_time()
        today = datetime.now().date()
        logging.info(f"🔔 Запуск утреннего напоминания. Текущее время: {current_time}")

        message = random.choice(MORNING_REMINDERS)

        sent_count = 0
        error_count = 0
        skipped_count = 0

        for user_id in subscribed_users.copy():
            # Проверяем, отправил ли пользователь уже задачи на сегодня
            last_keyword_date = user_keyword_dates.get(user_id)
            last_sport_keyword_date = user_sport_keyword_dates.get(user_id)

            progress_data = user_progress.get(user_id, {})
            sport_progress_data = user_sport_progress.get(user_id, {})

            tasks_list = progress_data.get("tasks_list", [])
            sport_tasks_list = sport_progress_data.get("tasks_list", [])

            # Проверяем различные условия, чтобы определить, нужно ли отправлять напоминание
            has_it_tasks_today = last_keyword_date == today or (tasks_list and len(tasks_list) > 0)
            has_sport_tasks_today = last_sport_keyword_date == today or (sport_tasks_list and len(sport_tasks_list) > 0)

            # Если пользователь уже отправил и IT и спортивные задачи сегодня - пропускаем
            if has_it_tasks_today and has_sport_tasks_today:
                skipped_count += 1
                logging.info(f"Пользователь {user_id} уже отправил все задачи сегодня - пропускаем")
                continue

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message
                )
                sent_count += 1
                logging.info(f"Утреннее напоминание отправлено пользователю {user_id}")

                # Небольшая задержка чтобы не превысить лимиты Telegram
                await asyncio.sleep(0.1)

            except Exception as e:
                error_count += 1
                logging.error(f"Ошибка отправки утреннего напоминания пользователю {user_id}: {e}")

                # Если пользователь заблокировал бота, удаляем его из подписчиков
                if "bot was blocked" in str(e).lower():
                    subscribed_users.discard(user_id)
                    logging.info(f"Пользователь {user_id} удален из подписчиков (заблокировал бота)")

        logging.info(
            f"✅ Утренние напоминания отправлены. Успешно: {sent_count}, Ошибок: {error_count}, Пропущено: {skipped_count}")

    except Exception as e:
        logging.error(f"Критическая ошибка в утреннем напоминании: {e}")


# ========== КОМАНДЫ БОТА ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - подписка на уведомления"""
    user_id = update.effective_user.id
    subscribed_users.add(user_id)

    if user_id not in user_progress:
        user_progress[user_id] = {
            "last_progress_date": None,
            "tasks_count": 0,
            "wrote_progress": False,
            "tasks_list": []
        }

    if user_id not in user_sport_progress:
        user_sport_progress[user_id] = {
            "last_progress_date": None,
            "tasks_count": 0,
            "wrote_progress": False,
            "tasks_list": []
        }

    keyboard = [
        ["/status", "/mytasks"],
        ["/mysport", "/mygoals"],
        ["/stop", "/help"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = (
        "🖕 Добро пожаловать в ад, уебок!\n\n"
        "🤖 **Как не быть мудаком:**\n"
        "1. Пиши в теме IT свой список задач\n"
        "2. Пиши в теме Спорт свой спортивный план\n"
        "3. Для месячных целей - в теме 'задачи на месяц'\n\n"
        "📊 **Как отчитываться как не полный еблан:**\n"
        f"• '{PROGRESS_KEYWORD}: выполнил N задач' - IT отчет\n"
        f"• '{SPORT_PROGRESS_KEYWORD}: выполнил N упражнений' - спорт\n"
        f"• '{KEYWORD}' или '{SPORT_KEYWORD}' - полное выполнение\n\n"
        "⏰ **Когда я буду ебать твой мозг:**\n"
        "• 10:00 - утренний пиздец\n"
        "• Каждый час - проверка не проебываешь ли время\n"
        "• 00:00 - новый день, новый пиздец\n\n"
        "🎯 **Я буду постоянно напоминать тебе что ты мудак если не выполнишь задачи!**\n\n"
        "👇 Тыкай кнопки внизу, долбоеб"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    logging.info(f"Пользователь {user_id} подписался")


async def mytasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mytasks - показать список IT задач пользователя"""
    user_id = update.effective_user.id
    progress_data = user_progress.get(user_id, {})
    tasks_list = progress_data.get("tasks_list", [])

    if not tasks_list:
        tasks_text = (
            "🖕 У тебя еще нет списка IT задач, долбоеб.\n\n"
            "Напиши в теме IT свой список задач в формате:\n"
            "1. Первая задача\n"
            "2. Вторая задача\n"
            "3. Третья задача\n\n"
            "Я сам посчитаю сколько тебе страдать!"
        )
    else:
        tasks_text = "🖕 Твои IT задачи на сегодня:\n\n"
        for task_num, task_text in sorted(tasks_list, key=lambda x: x[0]):
            tasks_text += f"{task_num}. {task_text}\n"

        total_tasks = get_total_tasks_from_list(tasks_list)
        tasks_text += f"\nВсего IT задач: {total_tasks}"
        tasks_text += f"\n\nПиши '{PROGRESS_KEYWORD}: выполнил N задач' в теме IT когда сделаешь часть, мудила!"

    await update.message.reply_text(tasks_text)


async def mysport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mysport - показать спортивный план пользователя"""
    user_id = update.effective_user.id
    progress_data = user_sport_progress.get(user_id, {})
    tasks_list = progress_data.get("tasks_list", [])

    if not tasks_list:
        tasks_text = (
            "🖕 У тебя еще нет спортивного плана, слабак.\n\n"
            "Напиши в теме Спорт свой план в формате:\n"
            "1. Первое упражнение\n"
            "2. Второе упражнение\n"
            "3. Третье упражнение\n\n"
            "Я сам посчитаю сколько тебе мучаться!"
        )
    else:
        tasks_text = "🖕 Твой спортивный план на сегодня:\n\n"
        for task_num, task_text in sorted(tasks_list, key=lambda x: x[0]):
            tasks_text += f"{task_num}. {task_text}\n"

        total_tasks = get_total_tasks_from_list(tasks_list)
        tasks_text += f"\nВсего упражнений: {total_tasks}"
        tasks_text += f"\n\nПиши '{SPORT_PROGRESS_KEYWORD}: выполнил N упражнений' в теме Спорт когда сделаешь часть, дрищ!"

    await update.message.reply_text(tasks_text)


async def mygoals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mygoals - показать цели на месяц"""
    user_id = update.effective_user.id
    goals_data = user_monthly_goals.get(user_id, {})
    goals_list = goals_data.get("goals_list", [])
    created_date = goals_data.get("created_date")

    if not goals_list:
        goals_text = (
            "🖕 У тебя еще нет целей на месяц, бесхребетный мудак.\n\n"
            "Напиши в теме 'задачи на месяц' свои цели в формате:\n"
            "Цели на месяц:\n"
            "1. Первая цель\n"
            "2. Вторая цель\n"
            "3. Третья цель\n\n"
            "Я буду каждый день напоминать какой ты ничтожный если не двигаешься к целям!"
        )
    else:
        goals_text = "🖕 Твои цели на месяц:\n\n"
        for goal_num, goal_text in sorted(goals_list, key=lambda x: x[0]):
            goals_text += f"{goal_num}. {goal_text}\n"

        if created_date:
            goals_text += f"\n📅 Цели установлены: {created_date.strftime('%d.%m.%Y')}"

        goals_text += f"\n\nВсего целей: {len(goals_list)}"

    await update.message.reply_text(goals_text)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stop - отписка от уведомлений"""
    user_id = update.effective_user.id
    if user_id in subscribed_users:
        subscribed_users.remove(user_id)
        await update.message.reply_text("🖕 Отписался от уведомлений, слабак? Ну и хуй с тобой!")
    else:
        await update.message.reply_text("Ты и так не подписан, мудила")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - показывает все доступные команды с кнопками"""
    keyboard = [
        ["/status", "/mytasks"],
        ["/mysport", "/mygoals"],
        ["/stop", "/help"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    help_text = (
        "🖕 ДОСТУПНЫЕ КОМАНДЫ, МУДАК:\n\n"
        "📊 **Статус и отчеты:**\n"
        "/status - твой статус по всем задачам\n"
        "/mytasks - показать твои IT задачи\n"
        "/mysport - показать твой спортивный план\n"
        "/mygoals - показать цели на месяц\n\n"
        "⚙️ **Управление:**\n"
        "/stop - отписаться от уведомлений (для слабаков)\n"
        "/help - показать это сообщение\n\n"
        "⏰ **Когда я буду ебать твой мозг:**\n"
        "• 10:00 - утренний пиздец\n"
        "• Каждый час - проверка выполнения\n"
        "• 00:00 - сброс на новый день\n\n"
        "📝 **Как не быть мудаком:**\n"
        "1. Пиши списки задач в соответствующих темах\n"
        "2. Отчитывайся о прогрессе кодовыми словами\n"
        "3. Получай напоминания что ты чмо!"
    )

    await update.message.reply_text(
        help_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - показать персональный статус"""
    user_id = update.effective_user.id
    today = datetime.now().date()

    last_keyword_date = user_keyword_dates.get(user_id)
    last_sport_keyword_date = user_sport_keyword_dates.get(user_id)
    progress_data = user_progress.get(user_id, {})
    sport_progress_data = user_sport_progress.get(user_id, {})
    tasks_list = progress_data.get("tasks_list", [])
    sport_tasks_list = sport_progress_data.get("tasks_list", [])
    total_tasks = get_total_tasks_from_list(tasks_list)
    total_sport_tasks = get_total_tasks_from_list(sport_tasks_list)

    goals_data = user_monthly_goals.get(user_id, {})
    goals_list = goals_data.get("goals_list", [])

    status_text = "🖕 ТВОЙ СТАТУС, МУДАК\n\n"

    if last_keyword_date == today:
        status_text += (
            f"✅ IT задачи: ВЫПОЛНЕНЫ!\n"
            f"• Ты не такой уж и еблан, хотя я все еще сомневаюсь\n"
            f"• Сегодня по IT тебя ебать не буду\n\n"
        )
    else:
        status_text += (
            f"❌ IT задачи: ЕЩЕ НЕ ВЫПОЛНЕНЫ!\n"
            f"• Используй '{KEYWORD}' когда закончишь страдать\n\n"
        )

    if last_sport_keyword_date == today:
        status_text += (
            f"✅ Спортивные задачи: ВЫПОЛНЕНЫ!\n"
            f"• Ты не такой уж и дрищ\n"
            f"• Сегодня по спорту тебя ебать не буду\n\n"
        )
    else:
        status_text += (
            f"❌ Спортивные задачи: ЕЩЕ НЕ ВЫПОЛНЕНЫ!\n"
            f"• Используй '{SPORT_KEYWORD}' когда закончишь мучаться\n\n"
        )

    if progress_data.get("wrote_progress"):
        remaining = progress_data.get("tasks_count", total_tasks)
        status_text += f"📊 IT прогресс:\n• Осталось задач: {remaining}\n"
    else:
        status_text += f"📊 IT прогресс:\n• Промежуточный отчет не отправлял, мудила\n"

    if sport_progress_data.get("wrote_progress"):
        remaining_sport = sport_progress_data.get("tasks_count", total_sport_tasks)
        status_text += f"🏃 Спортивный прогресс:\n• Осталось упражнений: {remaining_sport}\n"

    status_text += f"\n📋 IT задачи: {total_tasks if tasks_list else 'не заданы, долбоеб'}"
    status_text += f"\n🏃 Спортивные задачи: {total_sport_tasks if sport_tasks_list else 'не заданы, слабак'}"

    if goals_list:
        status_text += f"\n🎯 Цели на месяц: {len(goals_list)} целей"
        if goals_data.get("created_date"):
            status_text += f" (с {goals_data['created_date'].strftime('%d.%m.%Y')})"
    else:
        status_text += f"\n🎯 Цели на месяц: не установлены, бесхребетный мудак"

    status_text += f"\n\n📈 Общая статистика:"
    status_text += f"\n• Подписчиков: {len(subscribed_users)} уебков"
    status_text += f"\n• Выполнили IT сегодня: {count_users_written_today()} не лохов"
    status_text += f"\n• Выполнили спорт сегодня: {count_sport_users_written_today()} не дрищей"

    await update.message.reply_text(status_text)


# ========== ОБРАБОТКА СООБЩЕНИЙ ИЗ ГРУППЫ ==========
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения из группы и ищет кодовые слова и списки задач"""
    if update.effective_chat.id == GROUP_ID:
        message_text = update.message.text or ""
        user_id = update.effective_user.id

        message_thread_id = getattr(update.message, 'message_thread_id', None)

        if message_thread_id == TOPIC_ID:
            await handle_daily_tasks(update, message_text, user_id)
        elif message_thread_id == SPORT_TOPIC_ID:
            await handle_sport_tasks(update, message_text, user_id)
        elif message_thread_id == MONTHLY_TOPIC_ID:
            await handle_monthly_goals(update, message_text, user_id)


async def handle_daily_tasks(update: Update, message_text: str, user_id: int):
    """Обрабатывает сообщения в теме IT задач"""
    tasks_list = parse_tasks_from_message(message_text)
    if tasks_list:
        total_tasks = get_total_tasks_from_list(tasks_list)
        if total_tasks > 0:
            if user_id not in user_progress:
                user_progress[user_id] = {
                    "last_progress_date": None,
                    "tasks_count": total_tasks,
                    "wrote_progress": False,
                    "tasks_list": tasks_list
                }
            else:
                user_progress[user_id].update({
                    "tasks_count": total_tasks,
                    "tasks_list": tasks_list
                })

            logging.info(f"Пользователь {user_id} установил IT список из {total_tasks} задач")

            try:
                await update.message.reply_text(
                    f"📋 @{update.effective_user.username or update.effective_user.first_name} "
                    f"установил(а) IT список из {total_tasks} задач! Готовься страдать, мудила!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logging.error(f"Ошибка отправки подтверждения IT списка задач: {e}")

    # Гибкая проверка ключевого слова для полного выполнения IT задач
    keyword_patterns = [
        r'выполнил\s+все\s+задачи',
        r'все\s+задачи\s+выполнены',
        r'задачи\s+готовы',
        r'все\s+сделал',
        r'все\s+готово',
        r'все\s+задачи\s+сделаны',
        r'закончил\s+все\s+задачи',
        r'готовы\s+все\s+задачи'
    ]

    has_keyword = any(re.search(pattern, message_text.lower()) for pattern in keyword_patterns)

    if has_keyword:
        today = datetime.now().date()
        user_keyword_dates[user_id] = today
        logging.info(f"Пользователь {user_id} выполнил все IT задачи, дата: {today}")

        try:
            response = random.choice(COMPLETED_IT_TASKS)
            await update.message.reply_text(
                f"🎉 @{update.effective_user.username or update.effective_user.first_name} {response}",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки IT подтверждения: {e}")

    elif any(re.search(pattern, message_text.lower()) for pattern in [
        r'промежуточный', r'прмежуточный', r'промежут', r'итог', r'итг', r'отчет'
    ]):
        await handle_progress_report(update, message_text, user_id, is_sport=False)


async def handle_sport_tasks(update: Update, message_text: str, user_id: int):
    """Обрабатывает сообщения в теме спортивных задач"""
    tasks_list = parse_tasks_from_message(message_text)
    if tasks_list:
        total_tasks = get_total_tasks_from_list(tasks_list)
        if total_tasks > 0:
            if user_id not in user_sport_progress:
                user_sport_progress[user_id] = {
                    "last_progress_date": None,
                    "tasks_count": total_tasks,
                    "wrote_progress": False,
                    "tasks_list": tasks_list
                }
            else:
                user_sport_progress[user_id].update({
                    "tasks_count": total_tasks,
                    "tasks_list": tasks_list
                })

            logging.info(f"Пользователь {user_id} установил спортивный список из {total_tasks} упражнений")

            try:
                await update.message.reply_text(
                    f"🏃 @{update.effective_user.username or update.effective_user.first_name} "
                    f"установил(а) спортивный план из {total_tasks} упражнений! Готовься мучаться, дрищ!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logging.error(f"Ошибка отправки подтверждения спортивного плана: {e}")

    # Гибкая проверка ключевого слова для полного выполнения спортивных задач
    keyword_patterns = [
        r'выполнил\s+все\s+спортивные',
        r'все\s+спортивные\s+готовы',
        r'спорт\s+готов',
        r'спортивные\s+задачи\s+выполнены',
        r'упражнения\s+готовы',
        r'закончил\s+тренировку',
        r'тренировка\s+закончена'
    ]

    has_keyword = any(re.search(pattern, message_text.lower()) for pattern in keyword_patterns)

    if has_keyword:
        today = datetime.now().date()
        user_sport_keyword_dates[user_id] = today
        logging.info(f"Пользователь {user_id} выполнил все спортивные задачи, дата: {today}")

        try:
            response = random.choice(COMPLETED_SPORT_TASKS)
            await update.message.reply_text(
                f"💪 @{update.effective_user.username or update.effective_user.first_name} {response}",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки спортивного подтверждения: {e}")

    elif any(re.search(pattern, message_text.lower()) for pattern in [
        r'спортивный', r'спртивный', r'спорт', r'упражнен'
    ]):
        await handle_progress_report(update, message_text, user_id, is_sport=True)


async def handle_monthly_goals(update: Update, message_text: str, user_id: int):
    """Обрабатывает сообщения в теме месячных целей"""
    goals_list = parse_monthly_goals(message_text)

    if goals_list:
        today = datetime.now().date()

        user_monthly_goals[user_id] = {
            "goals_list": goals_list,
            "created_date": today
        }

        logging.info(f"Пользователь {user_id} установил {len(goals_list)} целей на месяц")

        try:
            await update.message.reply_text(
                f"🎯 @{update.effective_user.username or update.effective_user.first_name} "
                f"установил(а) {len(goals_list)} целей на месяц! "
                f"Теперь я буду каждый день напоминать какой ты уебок если не двигаешься к ним!",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки подтверждения целей: {e}")


async def handle_progress_report(update: Update, message_text: str, user_id: int, is_sport: bool = False):
    """Обрабатывает промежуточные отчеты о прогрессе с учетом орфографических ошибок"""
    if is_sport:
        progress_dict = user_sport_progress
        keyword = SPORT_PROGRESS_KEYWORD
        task_type = "упражнений"
        progress_data = user_sport_progress.get(user_id, {})
        progress_responses = PROGRESS_RESPONSES_SPORT
    else:
        progress_dict = user_progress
        keyword = PROGRESS_KEYWORD
        task_type = "задач"
        progress_data = user_progress.get(user_id, {})
        progress_responses = PROGRESS_RESPONSES_IT

    # Более гибкое распознавание ключевых слов с ошибками
    keyword_patterns = [
        r'промежуточный\s+итог',
        r'промежуточный',
        r'прмежуточный',
        r'промежутчный',
        r'промежуточныи',
        r'промежут',
        r'прожамточный',
        r'прожамуточный',
        r'итог',
        r'итг',
        r'отчет',
        r'отчёт'
    ]

    sport_keyword_patterns = [
        r'спортивный\s+промежуточный\s+итог',
        r'спортивный\s+итог',
        r'спортивный',
        r'спорт',
        r'спртивный',
        r'спортивныи'
    ]

    # Проверяем, содержит ли сообщение любой из вариантов ключевых слов
    has_keyword = False
    if is_sport:
        for pattern in sport_keyword_patterns:
            if re.search(pattern, message_text.lower()):
                has_keyword = True
                break
    else:
        for pattern in keyword_patterns:
            if re.search(pattern, message_text.lower()):
                has_keyword = True
                break

    if not has_keyword:
        return

    # Гибкое извлечение количества выполненных задач
    number_patterns = [
        r'выполнил\s+(\d+)\s+' + task_type,  # выполнил 2 задач
        r'сделал\s+(\d+)\s+' + task_type,  # сделал 2 задач
        r'закончил\s+(\d+)\s+' + task_type,  # закончил 2 задач
        r'готов[оы]?\s+(\d+)\s+' + task_type,  # готово 2 задач
        r'(\d+)\s+' + task_type,  # 2 задач
        r'выполнил\s+задачу?\s*(\d+)',  # выполнил задачу 2
        r'сделал\s+задачу?\s*(\d+)',  # сделал задачу 2
        r'задача?\s*(\d+)\s+готов[аоы]?',  # задача 2 готова
        r'(\d+)\s+из',  # 2 из
        r'(\d+)\s+задач',  # 2 задач
        r'(\d+)\s+упражнен',  # 2 упражнен
        r'(\d+)\s+упражнени'  # 2 упражнения
    ]

    completed_tasks = None
    for pattern in number_patterns:
        match = re.search(pattern, message_text.lower())
        if match:
            try:
                completed_tasks = int(match.group(1))
                break
            except (ValueError, IndexError):
                continue

    # Если не нашли число в стандартных паттернах, ищем любое число в сообщении
    if completed_tasks is None:
        numbers = re.findall(r'\b(\d+)\b', message_text)
        if numbers:
            completed_tasks = int(numbers[0])

    if completed_tasks is None:
        try:
            topic_name = "Спорт" if is_sport else "IT"
            await update.message.reply_text(
                f"❓ @{update.effective_user.username or update.effective_user.first_name}, "
                f"я не понял, сколько {task_type} ты выполнил, долбоеб. "
                f"Пиши например: 'Выполнил 2 {task_type}' или 'Сделал задачу 3'",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки запроса уточнения: {e}")
        return

    today = datetime.now().date()

    tasks_list = progress_data.get("tasks_list", [])
    total_tasks = get_total_tasks_from_list(tasks_list)

    if total_tasks == 0:
        try:
            topic_name = "Спорт" if is_sport else "IT"
            await update.message.reply_text(
                f"⚠️ @{update.effective_user.username or update.effective_user.first_name}, "
                f"сначала напиши в теме {topic_name} свой список в формате: 1. Задача 1, 2. Задача 2, ..., мудила!",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки предупреждения: {e}")
        return

    if user_id not in progress_dict:
        progress_dict[user_id] = {
            "last_progress_date": today,
            "tasks_count": total_tasks,
            "wrote_progress": True,
            "tasks_list": tasks_list
        }

    remaining_tasks = total_tasks - completed_tasks

    # Защита от отрицательного количества задач
    if remaining_tasks < 0:
        remaining_tasks = 0
        completed_tasks = total_tasks

    progress_dict[user_id].update({
        "last_progress_date": today,
        "tasks_count": remaining_tasks,
        "wrote_progress": True
    })

    if remaining_tasks > 0:
        response_template = random.choice(progress_responses)
        response = response_template.format(
            completed=completed_tasks,
            total=total_tasks,
            remaining=remaining_tasks
        )
    else:
        if is_sport:
            response = random.choice(COMPLETED_SPORT_TASKS)
            user_sport_keyword_dates[user_id] = today
            logging.info(f"Пользователь {user_id} автоматически отмечен как выполнивший все спортивные задачи")
        else:
            response = random.choice(COMPLETED_IT_TASKS)
            user_keyword_dates[user_id] = today
            logging.info(f"Пользователь {user_id} автоматически отмечен как выполнивший все IT задачи")

    try:
        await update.message.reply_text(
            f"@{update.effective_user.username or update.effective_user.first_name} {response}",
            reply_to_message_id=update.message.message_id
        )
        logging.info(
            f"Пользователь {user_id} отправил {'спортивный ' if is_sport else ''}промежуточный отчет: {completed_tasks} из {total_tasks} {task_type}")
    except Exception as e:
        logging.error(f"Ошибка отправки ответа на промежуточный итог: {e}")


# ========== ПРОВЕРКА И НАПОМИНАНИЯ ==========
async def check_keyword_activity(context: ContextTypes.DEFAULT_TYPE):
    """Периодически проверяет для каждого пользователя и отправляет напоминания"""
    if not should_send_reminders():
        return

    today = datetime.now().date()

    for user_id in subscribed_users.copy():
        last_keyword_date = user_keyword_dates.get(user_id)
        progress_data = user_progress.get(user_id, {})
        tasks_list = progress_data.get("tasks_list", [])
        total_tasks = get_total_tasks_from_list(tasks_list)

        if total_tasks > 0 and last_keyword_date != today:
            if progress_data.get("wrote_progress"):
                last_progress_date = progress_data.get("last_progress_date")
                if last_progress_date == today:
                    continue
                else:
                    await notify_user(context, user_id, is_progress_user=False, task_type="it")
            else:
                await notify_user(context, user_id, is_progress_user=False, task_type="it")

        last_sport_keyword_date = user_sport_keyword_dates.get(user_id)
        sport_progress_data = user_sport_progress.get(user_id, {})
        sport_tasks_list = sport_progress_data.get("tasks_list", [])
        total_sport_tasks = get_total_tasks_from_list(sport_tasks_list)

        if total_sport_tasks > 0 and last_sport_keyword_date != today:
            if sport_progress_data.get("wrote_progress"):
                last_sport_progress_date = sport_progress_data.get("last_progress_date")
                if last_sport_progress_date == today:
                    continue
                else:
                    await notify_user(context, user_id, is_progress_user=False, task_type="sport")
            else:
                await notify_user(context, user_id, is_progress_user=False, task_type="sport")


async def check_progress_users(context: ContextTypes.DEFAULT_TYPE):
    """Отдельная проверка для пользователей, которые писали промежуточный итог"""
    if not should_send_reminders():
        return

    today = datetime.now().date()

    for user_id in subscribed_users.copy():
        progress_data = user_progress.get(user_id, {})
        last_keyword_date = user_keyword_dates.get(user_id)
        tasks_list = progress_data.get("tasks_list", [])
        total_tasks = get_total_tasks_from_list(tasks_list)

        if (total_tasks > 0 and last_keyword_date != today and
                progress_data.get("wrote_progress") and
                progress_data.get("last_progress_date") == today):
            await notify_user(context, user_id, is_progress_user=True, task_type="it")

        sport_progress_data = user_sport_progress.get(user_id, {})
        last_sport_keyword_date = user_sport_keyword_dates.get(user_id)
        sport_tasks_list = sport_progress_data.get("tasks_list", [])
        total_sport_tasks = get_total_tasks_from_list(sport_tasks_list)

        if (total_sport_tasks > 0 and last_sport_keyword_date != today and
                sport_progress_data.get("wrote_progress") and
                sport_progress_data.get("last_progress_date") == today):
            await notify_user(context, user_id, is_progress_user=True, task_type="sport")


async def notify_user(context: ContextTypes.DEFAULT_TYPE, user_id: int, is_progress_user: bool = False,
                      task_type: str = "it"):
    """Отправляет уведомление конкретному пользователю"""
    try:
        if task_type == "sport":
            progress_data = user_sport_progress.get(user_id, {})
            tasks_list = progress_data.get("tasks_list", [])
            total_tasks = get_total_tasks_from_list(tasks_list)
            remaining_tasks = progress_data.get("tasks_count", total_tasks)
            last_keyword_date = user_sport_keyword_dates.get(user_id)
            keyword = SPORT_KEYWORD
            progress_keyword = SPORT_PROGRESS_KEYWORD
            topic_name = "Спорт"
            task_word = "упражнений"
            icon = "🏃"
        else:
            progress_data = user_progress.get(user_id, {})
            tasks_list = progress_data.get("tasks_list", [])
            total_tasks = get_total_tasks_from_list(tasks_list)
            remaining_tasks = progress_data.get("tasks_count", total_tasks)
            last_keyword_date = user_keyword_dates.get(user_id)
            keyword = KEYWORD
            progress_keyword = PROGRESS_KEYWORD
            topic_name = "IT"
            task_word = "задач"
            icon = "📋"

        goals_data = user_monthly_goals.get(user_id, {})
        goals_list = goals_data.get("goals_list", [])

        today = datetime.now().date()

        if last_keyword_date == today:
            return

        if total_tasks == 0:
            message = random.choice(REMINDERS_NO_TASKS)
        elif is_progress_user:
            message_template = random.choice(PROGRESS_REMINDERS)
            message = message_template.format(remaining=remaining_tasks, total=total_tasks)
        else:
            message_template = random.choice(REMINDERS_WITH_TASKS)
            message = message_template.format(total=total_tasks)

        if goals_list:
            message += "\n\n🎯 Не забудь про свои ебучие цели на месяц:\n"
            for goal_num, goal_text in sorted(goals_list, key=lambda x: x[0])[:3]:
                message += f"• {goal_text}\n"
            if len(goals_list) > 3:
                message += f"• ... и еще {len(goals_list) - 3} целей\n"

        message += "\nДомой Волтер"

        await context.bot.send_message(
            chat_id=user_id,
            text=message
        )
        logging.info(f"Напоминание ({task_type}) отправлено пользователю {user_id}")

    except Exception as e:
        logging.error(f"Ошибка отправки пользователю {user_id}: {e}")
        if "bot was blocked" in str(e).lower():
            subscribed_users.discard(user_id)
            logging.info(f"Пользователь {user_id} удален из подписчиков (заблокировал бота)")


# ========== СБРОС СЧЕТЧИКА В ПОЛНОЧЬ ==========
async def reset_daily_counter(context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает статистику написания для всех пользователей каждый день в полночь"""
    global user_keyword_dates, user_sport_keyword_dates

    user_keyword_dates = {user_id: date for user_id, date in user_keyword_dates.items() if date < datetime.now().date()}
    user_sport_keyword_dates = {user_id: date for user_id, date in user_sport_keyword_dates.items() if
                                date < datetime.now().date()}

    for user_id in user_progress:
        user_progress[user_id]["wrote_progress"] = False
        tasks_list = user_progress[user_id].get("tasks_list", [])
        total_tasks = get_total_tasks_from_list(tasks_list)
        user_progress[user_id]["tasks_count"] = total_tasks

    for user_id in user_sport_progress:
        user_sport_progress[user_id]["wrote_progress"] = False
        sport_tasks_list = user_sport_progress[user_id].get("tasks_list", [])
        total_sport_tasks = get_total_tasks_from_list(sport_tasks_list)
        user_sport_progress[user_id]["tasks_count"] = total_sport_tasks

    logging.info("Ежедневный счетчик сброшен для всех пользователей")

    notification = random.choice(DAILY_RESET_MESSAGES)

    for user_id in subscribed_users.copy():
        user_notification = notification

        goals_data = user_monthly_goals.get(user_id, {})
        goals_list = goals_data.get("goals_list", [])

        if goals_list:
            user_notification += "\n\n🎯 Твои ебучие цели на месяц:\n"
            for goal_num, goal_text in sorted(goals_list, key=lambda x: x[0])[:3]:
                user_notification += f"• {goal_text}\n"
            if len(goals_list) > 3:
                user_notification += f"• ... и еще {len(goals_list) - 3} целей\n"
            user_notification += "\nПродолжай двигаться к своим целям, мудила! 💪"

        try:
            await context.bot.send_message(chat_id=user_id, text=user_notification)
        except Exception as e:
            logging.error(f"Ошибка отправки уведомления о новом дне пользователю {user_id}: {e}")


# ========== ОБРАБОТКА ОШИБОК ==========
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ошибки"""
    logging.error(f"Ошибка: {context.error}")


# ========== ЗАПУСК БОТА НА RAILWAY ==========
def main():
    """Запускает бота на Railway"""
    # Проверяем токен
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не установлен! Добавьте его в Variables на Railway")
        return

    # Запускаем Flask сервер для health checks
    keep_alive()
    logging.info("🔄 Flask сервер запущен для health checks")

    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("mytasks", mytasks_command))
    application.add_handler(CommandHandler("mysport", mysport_command))
    application.add_handler(CommandHandler("mygoals", mygoals_command))
    application.add_handler(CommandHandler("help", help_command))

    # Обработчик сообщений из групп
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.Chat(chat_id=GROUP_ID),
        handle_group_message
    ))

    # Обработчик ошибок
    application.add_error_handler(error_handler)

    # Запускаем периодические проверки
    job_queue = application.job_queue

    # Основная проверка
    job_queue.run_repeating(check_keyword_activity, interval=CHECK_INTERVAL, first=10)

    # Отдельная проверка для прогрессивных пользователей
    job_queue.run_repeating(check_progress_users, interval=PROGRESS_CHECK_INTERVAL, first=15)

    # Запускаем ежедневный сброс в полночь
    job_queue.run_daily(reset_daily_counter, time=datetime.strptime("00:00", "%H:%M").time())

    # ЗАПУСКАЕМ УТРЕННЕЕ НАПОМИНАНИЕ В 10:00 ПО ЕКАТЕРИНБУРГУ (UTC+5)
    # В UTC это будет 05:00 (10:00 - 5 часов)
    job_queue.run_daily(send_morning_reminder, time=datetime.strptime("05:00", "%H:%M").time())

    # Запускаем бота
    logging.info("🤖 Бот запускается на Railway...")
    application.run_polling()


if __name__ == "__main__":
    main()
