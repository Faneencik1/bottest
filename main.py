import os
import logging
import asyncio
import json
from datetime import datetime
from collections import defaultdict
from telegram import Update, InputFile, InputMediaPhoto, InputMediaVideo
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_date = datetime.now().strftime("%Y-%m-%d")
log_filename = f"log_{log_date}.txt"

file_handler = logging.FileHandler(log_filename, encoding="utf-8")
file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(file_handler)

# Отключаем лишние логи
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
CREATOR_CHAT_ID = int(os.getenv("CREATOR_CHAT_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ALLOWED_USERS = {CREATOR_CHAT_ID, 6811659941}

# Глобальные переменные для обработки медиагрупп
media_groups = defaultdict(list)
media_group_info = {}

# Файл для хранения заблокированных пользователей
BANNED_USERS_FILE = "banned_users.json"

# Загружаем заблокированных пользователей из файла
def load_banned_users():
    try:
        if os.path.exists(BANNED_USERS_FILE):
            with open(BANNED_USERS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке заблокированных пользователей: {e}")
    return {"user_ids": [], "usernames": []}

# Сохраняем заблокированных пользователей в файл
def save_banned_users(banned_users):
    try:
        with open(BANNED_USERS_FILE, "w") as f:
            json.dump(banned_users, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении заблокированных пользователей: {e}")

# Инициализируем список заблокированных пользователей
banned_users = load_banned_users()

async def process_media_group(media_group_id, context):
    await asyncio.sleep(3)  # Ждем 3 секунды для сбора всех медиа
    
    if media_group_id in media_groups and media_group_id in media_group_info:
        media_list = media_groups.pop(media_group_id)
        username, first_message = media_group_info.pop(media_group_id)
        
        if media_list:
            # Добавляем подпись к первому элементу
            if first_message.caption:
                media_class = type(media_list[0])
                media_list[0] = media_class(
                    media=media_list[0].media,
                    caption=first_message.caption
                )
            
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=f"Альбом из {len(media_list)} медиа от @{username}"
            )
            await context.bot.send_media_group(
                chat_id=CREATOR_CHAT_ID,
                media=media_list
            )
            await first_message.reply_text(
                f"Альбом из {len(media_list)} медиа получен! Скоро будет опубликован."
            )

async def forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        if not message:
            return

        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)

        # Проверяем, заблокирован ли пользователь
        if str(user_id) in banned_users["user_ids"] or (username and username.lower() in [u.lower() for u in banned_users["usernames"]]):
            await message.reply_text("Вы заблокированы и не можете отправлять сообщения.")
            return

        if message.text and message.text.strip() == "/start":
            await message.reply_text("Напиши свое сообщение или отправь фото.")
            return

        # Обработка медиагрупп (альбомов)
        if hasattr(message, 'media_group_id') and message.media_group_id:
            media_group_id = message.media_group_id
            
            if message.photo:
                media = InputMediaPhoto(media=message.photo[-1].file_id)
            elif message.video:
                media = InputMediaVideo(media=message.video.file_id)
            else:
                return

            # Для первого элемента в группе сохраняем информацию
            if media_group_id not in media_groups:
                media_group_info[media_group_id] = (username, message)
            
            media_groups[media_group_id].append(media)
            
            # Перезапускаем таймер обработки группы
            if hasattr(context, '_media_group_timer'):
                context._media_group_timer.cancel()
            
            context._media_group_timer = asyncio.create_task(
                process_media_group(media_group_id, context)
            )
            return

        # Обработка одиночных медиа
        if message.photo:
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=f"Фото от: @{username}"
            )
            await context.bot.send_photo(
                chat_id=CREATOR_CHAT_ID,
                photo=message.photo[-1].file_id,
                caption=message.caption if message.caption else None
            )
            await message.reply_text("Фото получено! Скоро будет опубликовано.")
            return

        if message.video:
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=f"Видео от: @{username}"
            )
            await context.bot.send_video(
                chat_id=CREATOR_CHAT_ID,
                video=message.video.file_id,
                caption=message.caption if message.caption else None
            )
            await message.reply_text("Видео получено! Скоро будет опубликовано.")
            return

        # Обработка голосовых сообщений
        if message.voice:
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=f"Голосовое сообщение от: @{username}"
            )
            await context.bot.send_voice(
                chat_id=CREATOR_CHAT_ID,
                voice=message.voice.file_id
            )
            await message.reply_text("Голосовое сообщение получено! Скоро будет опубликовано.")
            return

        # Обработка видеосообщений (кружков)
        if message.video_note:
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=f"Видеосообщение от: @{username}"
            )
            await context.bot.send_video_note(
                chat_id=CREATOR_CHAT_ID,
                video_note=message.video_note.file_id
            )
            await message.reply_text("Видеосообщение получено! Скоро будет опубликовано.")
            return

        # Обработка текста
        if message.text:
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=f"Сообщение от: @{username}"
            )
            await context.bot.send_message(
                chat_id=CREATOR_CHAT_ID,
                text=message.text
            )
            await message.reply_text("Сообщение получено! Скоро будет опубликовано.")
            return

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
        if message:
            await message.reply_text("Произошла ошибка при обработке вашего сообщения.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        if not message:
            return

        # Проверяем права пользователя
        if message.from_user.id not in ALLOWED_USERS:
            await message.reply_text("Недостаточно прав для выполнения этой команды.")
            return

        # Получаем аргументы команды
        args = context.args
        if not args:
            await message.reply_text("Использование: /ban <username или user_id>")
            return

        target = args[0].strip()
        
        # Определяем, это username или ID
        if target.startswith("@"):
            # Это username
            username = target[1:].lower()
            if username in [u.lower() for u in banned_users["usernames"]]:
                await message.reply_text(f"Пользователь @{username} уже заблокирован.")
            else:
                banned_users["usernames"].append(username)
                save_banned_users(banned_users)
                await message.reply_text(f"Пользователь @{username} успешно заблокирован.")
        else:
            # Пробуем как ID
            try:
                user_id = str(int(target))
                if user_id in banned_users["user_ids"]:
                    await message.reply_text(f"Пользователь с ID {user_id} уже заблокирован.")
                else:
                    banned_users["user_ids"].append(user_id)
                    save_banned_users(banned_users)
                    await message.reply_text(f"Пользователь с ID {user_id} успешно заблокирован.")
            except ValueError:
                await message.reply_text("Некорректный формат. Используйте /ban <username или user_id>")

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды ban: {e}", exc_info=True)
        if message:
            await message.reply_text("Произошла ошибка при выполнении команды.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        if not message:
            return

        # Проверяем права пользователя
        if message.from_user.id not in ALLOWED_USERS:
            await message.reply_text("Недостаточно прав для выполнения этой команды.")
            return

        # Получаем аргументы команды
        args = context.args
        if not args:
            await message.reply_text("Использование: /unban <username или user_id>")
            return

        target = args[0].strip()
        
        # Определяем, это username или ID
        if target.startswith("@"):
            # Это username
            username = target[1:].lower()
            if username not in [u.lower() for u in banned_users["usernames"]]:
                await message.reply_text(f"Пользователь @{username} не заблокирован.")
            else:
                banned_users["usernames"] = [u for u in banned_users["usernames"] if u.lower() != username]
                save_banned_users(banned_users)
                await message.reply_text(f"Пользователь @{username} успешно разблокирован.")
        else:
            # Пробуем как ID
            try:
                user_id = str(int(target))
                if user_id not in banned_users["user_ids"]:
                    await message.reply_text(f"Пользователь с ID {user_id} не заблокирован.")
                else:
                    banned_users["user_ids"].remove(user_id)
                    save_banned_users(banned_users)
                    await message.reply_text(f"Пользователь с ID {user_id} успешно разблокирован.")
            except ValueError:
                await message.reply_text("Некорректный формат. Используйте /unban <username или user_id>")

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды unban: {e}", exc_info=True)
        if message:
            await message.reply_text("Произошла ошибка при выполнении команды.")

async def list_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        if not message:
            return

        # Проверяем права пользователя
        if message.from_user.id not in ALLOWED_USERS:
            await message.reply_text("Недостаточно прав для выполнения этой команды.")
            return

        if not banned_users["user_ids"] and not banned_users["usernames"]:
            await message.reply_text("Список заблокированных пользователей пуст.")
            return

        response = "Заблокированные пользователи:\n"
        if banned_users["user_ids"]:
            response += "\nПо ID:\n" + "\n".join(banned_users["user_ids"])
        
        if banned_users["usernames"]:
            response += "\nПо username:\n@" + "\n@".join(banned_users["usernames"])

        await message.reply_text(response)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды list_banned: {e}", exc_info=True)
        if message:
            await message.reply_text("Произошла ошибка при выполнении команды.")

async def send_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("Недостаточно прав для доступа к логам.")
            return

    await update.message.reply_text(help_text, parse_mode='HTML')

        log_date = datetime.now().strftime("%Y-%m-%d")
        log_filename = f"log_{log_date}.txt"

        if os.path.exists(log_filename):
            with open(log_filename, "rb") as log_file:
                await update.message.reply_document(document=InputFile(log_file), filename=log_filename)
        else:
            await update.message.reply_text("Файл логов за сегодня не найден.")
    except Exception as e:
        logger.error(f"Ошибка при отправке логов: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
<b>Доступные команды:</b>

Для блокировки пользователя — /ban (username или ID)
Для разблокировки пользователя — /unban (username или ID)
Для получения списка заблокированных пользователей — /list_banned
Для получения логов — /log (не работает на данный момент)

Отправьте любое сообщение, фото или видео, и оно будет переслано администратору.
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики команд
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("log", send_log))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("list_banned", list_banned))
    app.add_handler(MessageHandler(filters.ALL, forward))
    
    # Обработчик ошибок
    app.add_error_handler(lambda update, context: logger.error(
        f"Необработанное исключение: {context.error}", 
        exc_info=True
    ))
    
    logger.info("Бот запущен ✅ с Webhook")
    app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        webhook_url=WEBHOOK_URL
    )
