import asyncio
import random
import re
from datetime import datetime, time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio
import logging
from typing import List, Set, Callable
import pickle

from config.config import TELEGRAM_BOT_TOKEN, TEXT_FILE_PATH, SCHEDULE_FILE_PATH, MOSCOW_TZ, RANDOM_STATE_FILE_PATH, USED_PARAGRAPHS_FILE_PATH
from config.logging_config import setup_logging
from errors import handle_error

# Настройка логирования
setup_logging()

# Отключение логов HTTP-запросов
logging.getLogger("httpx").setLevel(logging.WARNING)

# Применяем nest_asyncio для предотвращения ошибок с event loop
nest_asyncio.apply()

# Московский часовой пояс
moscow_tz = pytz.timezone(MOSCOW_TZ)

# Глобальные переменные
start_time = None  # Время запуска бота
scheduler = None  # Планировщик
schedule_times = []  # Время публикаций
random_state_file_path = RANDOM_STATE_FILE_PATH  # Путь к файлу состояния генератора случайных чисел
used_paragraphs_file_path = USED_PARAGRAPHS_FILE_PATH  # Путь к файлу использованных абзацев
MIN_PARAGRAPH_LENGTH = 50  # Минимальная длина абзаца для публикации

# Функция для чтения случайного абзаца из файла
def get_random_paragraph(file_path: str, used_paragraphs: Set[str]) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            text = file.read()
            paragraphs = re.split(r'\n\n', text)  # Разделение по двойным переносам строки
            paragraphs = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]  # Удаление пустых абзацев
            if not paragraphs:
                return "Нет доступных абзацев для публикации."
            
            # Удаляем уже использованные абзацы
            available_paragraphs = [paragraph for paragraph in paragraphs if paragraph not in used_paragraphs]
            if not available_paragraphs:
                return "Все абзацы уже были опубликованы. Сбросьте использованные абзацы командой /reset_used."
            
            # Фильтруем абзацы по длине
            available_paragraphs = [paragraph for paragraph in available_paragraphs if len(paragraph) >= MIN_PARAGRAPH_LENGTH]
            if not available_paragraphs:
                return f"Нет доступных абзацев длиной более {MIN_PARAGRAPH_LENGTH} символов."
            
            # Выбор случайного абзаца
            paragraph = random.choice(available_paragraphs)
            
            # Добавляем абзац в использованные
            used_paragraphs.add(paragraph)
            save_used_paragraphs(used_paragraphs)
            
            save_random_state()  # Сохраняем состояние генератора случайных чисел
            return remove_page_numbers(paragraph)
    except Exception as e:
        handle_error(e, "Ошибка при чтении файла")
        return f"Ошибка при чтении файла: {e}"

# Функция для удаления номеров страниц из текста
def remove_page_numbers(text: str) -> str:
    text = re.sub(r'\d+\s*["«»].*?["»]', '', text)
    text = re.sub(r'\d+\s*\.', '', text)  # Удаляем числа с точками
    text = re.sub(r'\d+', '', text)
    return text.strip()  # Удаляем лишние пробелы в начале и конце

# Функция для отправки поста в канал
async def send_post_to_channel(context: ContextTypes.DEFAULT_TYPE, get_paragraph_func: Callable):
    channel_id = "@thecreative_act"
    try:
        used_paragraphs = load_used_paragraphs()
        paragraph = get_paragraph_func(TEXT_FILE_PATH, used_paragraphs)
        if not paragraph:
            logging.error("Ошибка: текст для публикации пуст.")
            return
        await context.bot.send_message(chat_id=channel_id, text=paragraph)
    except Exception as e:
        handle_error(e, "Ошибка публикации", update=None, context=context)

# Немедленная публикация
async def immediate_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    used_paragraphs = load_used_paragraphs()
    paragraph = get_random_paragraph(TEXT_FILE_PATH, used_paragraphs)
    if not paragraph:
        await update.effective_message.reply_text("Ошибка: текст для публикации пуст.")
        return
    await send_post_to_channel(context, lambda file, used: paragraph)  # Передаем заранее подготовленный текст
    await update.effective_message.reply_text("Пост успешно опубликован!")

# Планирование постов
def schedule_posts(application: Application, times: List[time]):
    scheduler.remove_all_jobs()
    for t in times:
        scheduler.add_job(
            send_post_to_channel, "cron", hour=t.hour, minute=t.minute, args=[application, get_random_paragraph]
        )

# Клавиатура
def start_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Немедленная публикация", callback_data="post_immediately"),
            InlineKeyboardButton("Текущее время публикаций", callback_data="view_schedule")
        ],
        [
            InlineKeyboardButton("Сбросить использованные абзацы", callback_data="reset_used_paragraphs")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "post_immediately":
        await immediate_post(update, context)
    elif query.data == "view_schedule":
        times = ", ".join([t.strftime("%H:%M") for t in schedule_times])
        await query.edit_message_text(f"Текущее время публикаций: {times} по МСК")
    elif query.data == "reset_used_paragraphs":
        save_used_paragraphs(set())  # Сбрасываем использованные абзацы
        await query.edit_message_text("Использованные абзацы успешно сброшены.")

# Чтение расписания из файла
def read_schedule_from_file(file_path: str) -> List[time]:
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            lines = file.readlines()
            times = []
            for line in lines:
                try:
                    hour, minute = map(int, line.strip().split(":"))
                    if 0 <= hour < 24 and 0 <= minute < 60:
                        times.append(time(hour, minute))
                except ValueError:
                    continue
            return times or [time(9, 0), time(18, 0)]
    except FileNotFoundError:
        default_times = [time(9, 0), time(18, 0)]
        save_schedule_to_file(file_path, default_times)
        return default_times

# Сохранение расписания в файл
def save_schedule_to_file(file_path: str, times: List[time]):
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            for t in times:
                file.write(f"{t.strftime('%H:%M')}\n")
    except Exception as e:
        handle_error(e, "Ошибка записи в файл")

# Изменение расписания
async def set_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        times = context.args
        if not times:
            await update.message.reply_text("Укажите время публикации. Примеры: /settime 09:00 или /settime 09:00 18:00")
            return

        new_times = []
        for t in times:
            hour, minute = map(int, t.split(":"))
            new_times.append(time(hour, minute))

        # Если указано не 1 и не 2 времени – выдаём ошибку
        if len(new_times) not in (1, 2):
            await update.message.reply_text("Укажите ровно одно или два времени публикаций. Примеры: /settime 09:00 или /settime 09:00 18:00")
            return

        global schedule_times
        schedule_times = new_times

        save_schedule_to_file(SCHEDULE_FILE_PATH, schedule_times)
        schedule_posts(context.application, schedule_times)

        times_str = ", ".join(t.strftime('%H:%M') for t in schedule_times)
        await update.message.reply_text(f"Новое расписание: {times_str} по МСК")
    except ValueError:
        await update.message.reply_text("Ошибка: используйте формат ЧЧ:ММ, например: /settime 09:00 или /settime 09:00 18:00")


# Команда /start для отображения кнопок
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_start_time = start_time.strftime('%d. %m %H:%M:%S')  # Время запуска бота
    await update.message.reply_text(
        f"Бот запущен и готов к работе! Время запуска по МСК: {bot_start_time}. Используйте /settime для настройки времени.",
        reply_markup=start_keyboard()
    )

# Загрузка состояния генератора случайных чисел
def load_random_state():
    try:
        with open(random_state_file_path, "rb") as file:
            if file.read(1):  # Проверяем, есть ли данные в файле
                file.seek(0)  # Возвращаем указатель в начало файла
                state = pickle.load(file)
                random.setstate(state)
    except (FileNotFoundError, EOFError):
        pass

# Сохранение состояния генератора случайных чисел
def save_random_state():
    state = random.getstate()
    with open(random_state_file_path, "wb") as file:
        pickle.dump(state, file)

# Загрузка использованных абзацев
def load_used_paragraphs() -> Set[str]:
    try:
        with open(used_paragraphs_file_path, "rb") as file:
            return pickle.load(file)
    except (FileNotFoundError, EOFError):
        return set()

# Сохранение использованных абзацев
def save_used_paragraphs(used_paragraphs: Set[str]):
    with open(used_paragraphs_file_path, "wb") as file:
        pickle.dump(used_paragraphs, file)

# Сброс использованных абзацев
async def reset_used_paragraphs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_used_paragraphs(set())
    await update.message.reply_text("Использованные абзацы сброшены.")

# Основная функция
async def main():
    global start_time, scheduler, schedule_times
    start_time = datetime.now(moscow_tz)

    # Загрузка состояния генератора случайных чисел
    load_random_state()

    # Создание и запуск планировщика
    scheduler = AsyncIOScheduler(timezone=moscow_tz)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CommandHandler("settime", set_schedule))
    application.add_handler(CommandHandler("reset_used", reset_used_paragraphs))

    # Чтение расписания из файла при старте
    schedule_times = read_schedule_from_file(SCHEDULE_FILE_PATH)
    schedule_posts(application, schedule_times)

    scheduler.start()

    # Запуск Telegram бота
    await application.run_polling()

# Запуск программы
if __name__ == "__main__":
    asyncio.run(main())