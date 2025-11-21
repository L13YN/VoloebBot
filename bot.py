import asyncio
import logging
import re
import os
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

# ========== НОВАЯ ФУНКЦИЯ: УТРЕННЕЕ НАПОМИНАНИЕ ==========
async def send_morning_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет утреннее напоминание в 10 утра по Екатеринбургу"""
    try:
        current_time = get_ekaterinburg_time()
        logging.info(f"🔔 Запуск утреннего напоминания. Текущее время: {current_time}")
        
        message = (
            "Уебище, сделай уже список дел на день я хули тут сидеть без дела буду. Гандон.\n\n"
            "👇 Напиши в соответствующих темах:\n"
            "• В теме IT - список IT задач\n" 
            "• В теме Спорт - спортивный план\n"
            "• В теме месячных целей - цели на месяц\n\n"
            "Формат:\n1. Задача 1\n2. Задача 2\n3. Задача 3"
        )
        
        sent_count = 0
        error_count = 0
        
        for user_id in subscribed_users.copy():
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
        
        logging.info(f"✅ Утренние напоминания отправлены. Успешно: {sent_count}, Ошибок: {error_count}")
        
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
        "🔔 Вы подписались на персонализированные уведомления!\n\n"
        "🤖 **Как использовать:**\n"
        "1. Напишите в теме IT ваш список задач\n"
        "2. Напишите в теме Спорт ваш спортивный план\n"
        "3. Для месячных целей - в теме 'задачи на месяц'\n\n"
        "📊 **Для отчетов используйте:**\n"
        f"• '{PROGRESS_KEYWORD}: выполнил N задач' - IT отчет\n"
        f"• '{SPORT_PROGRESS_KEYWORD}: выполнил N упражнений' - спорт\n"
        f"• '{KEYWORD}' или '{SPORT_KEYWORD}' - полное выполнение\n\n"
        "⏰ **Расписание напоминаний:**\n"
        "• 10:00 - утреннее напоминание\n"
        "• Каждый час - проверка выполнения\n"
        "• 00:00 - сброс на новый день\n\n"
        "🎯 **Я буду напоминать вам о задачах и отслеживать прогресс!**\n\n"
        "👇 Используйте кнопки ниже для быстрого доступа к командам"
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
            "📋 У вас еще нет списка IT задач.\n\n"
            "Напишите в теме IT ваш список задач в формате:\n"
            "1. Первая задача\n"
            "2. Вторая задача\n"
            "3. Третья задача\n\n"
            "Я автоматически определю количество задач!"
        )
    else:
        tasks_text = "📋 Ваши IT задачи на сегодня:\n\n"
        for task_num, task_text in sorted(tasks_list, key=lambda x: x[0]):
            tasks_text += f"{task_num}. {task_text}\n"

        total_tasks = get_total_tasks_from_list(tasks_list)
        tasks_text += f"\nВсего IT задач: {total_tasks}"
        tasks_text += f"\n\nНапишите '{PROGRESS_KEYWORD}: выполнил N задач' в теме IT для отчета!"

    await update.message.reply_text(tasks_text)

async def mysport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mysport - показать спортивный план пользователя"""
    user_id = update.effective_user.id
    progress_data = user_sport_progress.get(user_id, {})
    tasks_list = progress_data.get("tasks_list", [])

    if not tasks_list:
        tasks_text = (
            "🏃 У вас еще нет спортивного плана.\n\n"
            "Напишите в теме Спорт ваш план в формате:\n"
            "1. Первое упражнение\n"
            "2. Второе упражнение\n"
            "3. Третье упражнение\n\n"
            "Я автоматически определю количество упражнений!"
        )
    else:
        tasks_text = "🏃 Ваш спортивный план на сегодня:\n\n"
        for task_num, task_text in sorted(tasks_list, key=lambda x: x[0]):
            tasks_text += f"{task_num}. {task_text}\n"

        total_tasks = get_total_tasks_from_list(tasks_list)
        tasks_text += f"\nВсего упражнений: {total_tasks}"
        tasks_text += f"\n\nНапишите '{SPORT_PROGRESS_KEYWORD}: выполнил N упражнений' в теме Спорт для отчета!"

    await update.message.reply_text(tasks_text)

async def mygoals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mygoals - показать цели на месяц"""
    user_id = update.effective_user.id
    goals_data = user_monthly_goals.get(user_id, {})
    goals_list = goals_data.get("goals_list", [])
    created_date = goals_data.get("created_date")

    if not goals_list:
        goals_text = (
            "🎯 У вас еще нет целей на месяц.\n\n"
            "Напишите в теме 'задачи на месяц' ваши цели в формате:\n"
            "Цели на месяц:\n"
            "1. Первая цель\n"
            "2. Вторая цель\n"
            "3. Третья цель\n\n"
            "Я буду напоминать о них каждый день!"
        )
    else:
        goals_text = "🎯 Ваши цели на месяц:\n\n"
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
        await update.message.reply_text("❌ Вы отписались от уведомлений")
    else:
        await update.message.reply_text("Вы и так не подписаны")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - показывает все доступные команды с кнопками"""
    keyboard = [
        ["/status", "/mytasks"],
        ["/mysport", "/mygoals"],
        ["/stop", "/help"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    help_text = (
        "🤖 ДОСТУПНЫЕ КОМАНДЫ:\n\n"
        "📊 **Статус и отчеты:**\n"
        "/status - ваш персональный статус по всем задачам\n"
        "/mytasks - показать ваши IT задачи\n"
        "/mysport - показать ваш спортивный план\n"
        "/mygoals - показать цели на месяц\n\n"
        "⚙️ **Управление:**\n"
        "/stop - отписаться от уведомлений\n"
        "/help - показать это сообщение\n\n"
        "⏰ **Расписание:**\n"
        "• 10:00 - утреннее напоминание\n"
        "• Каждый час - проверка выполнения\n"
        "• 00:00 - сброс на новый день\n\n"
        "📝 **Как использовать:**\n"
        "1. Пишите списки задач в соответствующих темах\n"
        "2. Отчитывайтесь о прогрессе кодовыми словами\n"
        "3. Получайте персонализированные напоминания!"
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

    status_text = "📊 ВАШ ПЕРСОНАЛЬНЫЙ СТАТУС\n\n"

    if last_keyword_date == today:
        status_text += (
            f"✅ IT задачи: ВЫПОЛНЕНЫ!\n"
            f"• Полный отчет отправлен\n"
            f"• Напоминаний по IT сегодня не будет\n\n"
        )
    else:
        status_text += (
            f"❌ IT задачи: ЕЩЕ НЕ ВЫПОЛНЕНЫ!\n"
            f"• Используйте '{KEYWORD}' когда выполните все\n\n"
        )

    if last_sport_keyword_date == today:
        status_text += (
            f"✅ Спортивные задачи: ВЫПОЛНЕНЫ!\n"
            f"• Полный отчет отправлен\n"
            f"• Напоминаний по спорту сегодня не будет\n\n"
        )
    else:
        status_text += (
            f"❌ Спортивные задачи: ЕЩЕ НЕ ВЫПОЛНЕНЫ!\n"
            f"• Используйте '{SPORT_KEYWORD}' когда выполните все\n\n"
        )

    if progress_data.get("wrote_progress"):
        remaining = progress_data.get("tasks_count", total_tasks)
        status_text += f"📊 IT прогресс:\n• Осталось задач: {remaining}\n"
    else:
        status_text += f"📊 IT прогресс:\n• Промежуточный отчет не отправлялся\n"

    if sport_progress_data.get("wrote_progress"):
        remaining_sport = sport_progress_data.get("tasks_count", total_sport_tasks)
        status_text += f"🏃 Спортивный прогресс:\n• Осталось упражнений: {remaining_sport}\n"

    status_text += f"\n📋 IT задачи: {total_tasks if tasks_list else 'не заданы'}"
    status_text += f"\n🏃 Спортивные задачи: {total_sport_tasks if sport_tasks_list else 'не заданы'}"

    if goals_list:
        status_text += f"\n🎯 Цели на месяц: {len(goals_list)} целей"
        if goals_data.get("created_date"):
            status_text += f" (с {goals_data['created_date'].strftime('%d.%m.%Y')})"
    else:
        status_text += f"\n🎯 Цели на месяц: не установлены"

    status_text += f"\n\n📈 Общая статистика:"
    status_text += f"\n• Подписчиков: {len(subscribed_users)}"
    status_text += f"\n• Выполнили IT сегодня: {count_users_written_today()}"
    status_text += f"\n• Выполнили спорт сегодня: {count_sport_users_written_today()}"

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
                    f"установил(а) IT список из {total_tasks} задач!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logging.error(f"Ошибка отправки подтверждения IT списка задач: {e}")

    if KEYWORD.lower() in message_text.lower():
        today = datetime.now().date()
        user_keyword_dates[user_id] = today
        logging.info(f"Пользователь {user_id} выполнил все IT задачи, дата: {today}")

        try:
            await update.message.reply_text(
                f"🎉 @{update.effective_user.username or update.effective_user.first_name} "
                f"выполнил(а) все IT задачи на сегодня!",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки IT подтверждения: {e}")

    elif PROGRESS_KEYWORD.lower() in message_text.lower():
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
                    f"установил(а) спортивный план из {total_tasks} упражнений!",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logging.error(f"Ошибка отправки подтверждения спортивного плана: {e}")

    if SPORT_KEYWORD.lower() in message_text.lower():
        today = datetime.now().date()
        user_sport_keyword_dates[user_id] = today
        logging.info(f"Пользователь {user_id} выполнил все спортивные задачи, дата: {today}")

        try:
            await update.message.reply_text(
                f"💪 @{update.effective_user.username or update.effective_user.first_name} "
                f"выполнил(а) все спортивные задачи на сегодня! Молодец!",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки спортивного подтверждения: {e}")

    elif SPORT_PROGRESS_KEYWORD.lower() in message_text.lower():
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
                f"Теперь я буду напоминать о них каждый день!",
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"Ошибка отправки подтверждения целей: {e}")

async def handle_progress_report(update: Update, message_text: str, user_id: int, is_sport: bool = False):
    """Обрабатывает промежуточные отчеты о прогрессе"""
    if is_sport:
        progress_dict = user_sport_progress
        keyword = SPORT_PROGRESS_KEYWORD
        task_type = "упражнений"
        progress_data = user_sport_progress.get(user_id, {})
    else:
        progress_dict = user_progress
        keyword = PROGRESS_KEYWORD
        task_type = "задач"
        progress_data = user_progress.get(user_id, {})

    match = re.search(r'выполнил\s+(\d+)\s+' + task_type, message_text.lower())
    if match:
        completed_tasks = int(match.group(1))
        today = datetime.now().date()

        tasks_list = progress_data.get("tasks_list", [])
        total_tasks = get_total_tasks_from_list(tasks_list)

        if total_tasks == 0:
            try:
                topic_name = "Спорт" if is_sport else "IT"
                await update.message.reply_text(
                    f"⚠️ @{update.effective_user.username or update.effective_user.first_name}, "
                    f"сначала напишите в теме {topic_name} ваш список в формате: 1. Задача 1, 2. Задача 2, ...",
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
        progress_dict[user_id].update({
            "last_progress_date": today,
            "tasks_count": remaining_tasks,
            "wrote_progress": True
        })

        if remaining_tasks > 0:
            if is_sport:
                response = (
                    f"💪 @{update.effective_user.username or update.effective_user.first_name} "
                    f"Отлично! Осталось упражнений - {remaining_tasks}. Продолжай тренироваться! 🏃‍♂️"
                )
            else:
                response = (
                    f"✅ @{update.effective_user.username or update.effective_user.first_name} "
                    f"Красава, осталось задач - {remaining_tasks}. Продолжай в том же духе чмо! 💪"
                )
        else:
            if is_sport:
                response = (
                    f"🎉 @{update.effective_user.username or update.effective_user.first_name} "
                    f"выполнил(а) все спортивные задачи! Отличная работа! 💪"
                )
                user_sport_keyword_dates[user_id] = today
                logging.info(f"Пользователь {user_id} автоматически отмечен как выполнивший все спортивные задачи")
            else:
                response = (
                    f"🎉 @{update.effective_user.username or update.effective_user.first_name} "
                    f"выполнил(а) все IT задачи! Молодец! Но даже не думай гордиться собой, завтра будет новый день и новые задачи"
                )
                user_keyword_dates[user_id] = today
                logging.info(f"Пользователь {user_id} автоматически отмечен как выполнивший все IT задачи")

        try:
            await update.message.reply_text(
                response,
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
            message = (
                f"{icon} Напоминание!\n\n"
                f"Вы еще не установили {task_type} список на сегодня.\n"
                f"Напишите в теме {topic_name} ваш список в формате:\n"
                f"1. Задача 1\n2. Задача 2\n3. Задача 3\n\n"
            )
        elif is_progress_user:
            message = (
                f"{icon} Напоминание (каждые 1.5 часа)!\n\n"
                f"У вас осталось {remaining_tasks} из {total_tasks} {task_word}.\n"
                f"Не сбавляйте темп! 💪\n\n"
            )
        else:
            message = (
                f"{icon} Напоминание!\n\n"
                f"Сегодня ВЫ еще не отчитались о выполнении спортивных задач.\n"
                f"Всего {task_word}: {total_tasks}\n"
                f"Напишите '{progress_keyword}: выполнил N {task_word}' в теме {topic_name}!\n\n"
            )

        if goals_list:
            message += "🎯 Не забудьте про ваши цели на месяц:\n"
            for goal_num, goal_text in sorted(goals_list, key=lambda x: x[0])[:3]:
                message += f"• {goal_text}\n"
            if len(goals_list) > 3:
                message += f"• ... и еще {len(goals_list) - 3} целей\n"
            message += "\n"

        message += "Домой Волтер"

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

    notification = (
        "🔄 Начался новый день!\n\n"
        "Не забудьте:\n"
        "1. Написать в теме IT ваш список задач\n"
        "2. Написать в теме Спорт ваш спортивный план\n"
        "3. Отчитываться о прогрессе:\n"
        f"• '{PROGRESS_KEYWORD}: выполнил N задач' - для IT\n"
        f"• '{SPORT_PROGRESS_KEYWORD}: выполнил N упражнений' - для спорта\n\n"
    )

    for user_id in subscribed_users.copy():
        user_notification = notification

        goals_data = user_monthly_goals.get(user_id, {})
        goals_list = goals_data.get("goals_list", [])

        if goals_list:
            user_notification += "🎯 Ваши цели на месяц:\n"
            for goal_num, goal_text in sorted(goals_list, key=lambda x: x[0])[:3]:
                user_notification += f"• {goal_text}\n"
            if len(goals_list) > 3:
                user_notification += f"• ... и еще {len(goals_list) - 3} целей\n"
            user_notification += "\nПродолжайте двигаться к вашим целям! 💪"

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
