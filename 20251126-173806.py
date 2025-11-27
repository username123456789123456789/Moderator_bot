# aiogram_bot.py
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ChatPermissions,
    InputFile,
    InputMediaPhoto,
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import ReplyKeyboardRemove
from aiogram.filters import Command

# =================== Config (БЕЗОПАСНО) ===================
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("8232627546:AAHfb6P_BwQ8lJbhaKH7OkK_sCkNFlBgPD8")
OWNER_ID = int(os.getenv("7134895036"))
TIMERS_FILE = "timers.json"

if not BOT_TOKEN or not OWNER_ID:
    raise ValueError("Установи BOT_TOKEN и OWNER_ID в файле .env!")

# =================== Init ===================
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Переводчик (googletrans)
from googletrans import Translator
translator = Translator()

# =================== Utilities ===================
def is_supergroup(chat_id: int) -> bool:
    return chat_id < -1000000000000

# =================== Timers (mute/ban) ===================
timers: Dict[str, Dict[str, str]] = {"mute": {}, "ban": {}}
tasks: Dict[str, asyncio.Task] = {}

def load_timers():
    global timers
    if os.path.exists(TIMERS_FILE):
        try:
            with open(TIMERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                timers["mute"] = data.get("mute", {})
                timers["ban"] = data.get("ban", {})
        except Exception as e:
            print(f"[!] Ошибка загрузки таймеров: {e}")

def save_timers():
    try:
        with open(TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(timers, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Ошибка сохранения таймеров: {e}")

def key_for(chat_id: int, user_id: int) -> str:
    return f"{chat_id}-{user_id}"

async def safe_unmute(chat_id: int, user_id: int, name: str = "User"):
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            )
        )
        await bot.send_message(chat_id, f"Unmuted {name} автоматически.")
    except:
        pass

async def safe_unban(chat_id: int, user_id: int, name: str = "User"):
    try:
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        await bot.send_message(chat_id, f"Unbanned {name} автоматически.")
    except:
        pass

def add_timer(timer_type: str, chat_id: int, user_id: int, end_time: datetime):
    k = key_for(chat_id, user_id)
    timers[timer_type][k] = end_time.isoformat()
    save_timers()

    task_name = f"{timer_type}:{chat_id}:{user_id}"
    if task_name in tasks:
        tasks[task_name].cancel()
    
    tasks[task_name] = asyncio.create_task(_timer_task(timer_type, chat_id, user_id, end_time))

def remove_timer(timer_type: str, chat_id: int, user_id: int):
    k = key_for(chat_id, user_id)
    timers[timer_type].pop(k, None)
    save_timers()
    task_name = f"{timer_type}:{chat_id}:{user_id}"
    if task_name in tasks:
        tasks[task_name].cancel()
        tasks.pop(task_name, None)

async def _timer_task(timer_type: str, chat_id: int, user_id: int, end_time: datetime):
    delay = (end_time - datetime.now(timezone.utc)).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    
    if timer_type == "mute":
        await safe_unmute(chat_id, user_id)
    elif timer_type == "ban":
        await safe_unban(chat_id, user_id)
    
    remove_timer(timer_type, chat_id, user_id)

def restore_timers():
    for ttype in ["mute", "ban"]:
        for key, iso in list(timers[ttype].items()):
            try:
                chat_id, user_id = map(int, key.split("-"))
                end_time = datetime.fromisoformat(iso)
                if end_time > datetime.now(timezone.utc):
                    add_timer(ttype, chat_id, user_id, end_time)
                else:
                    remove_timer(ttype, chat_id, user_id)
            except:
                timers[ttype].pop(key, None)
    save_timers()

load_timers()
restore_timers()

# =================== Проверка админа ===================
async def is_admin_or_owner(chat_id: int, user_id: int) -> bool:
    if user_id == 7134895036:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

# =================== Хендлеры ===================

# Удаление служебных сообщений
@dp.message(F.new_chat_members | F.left_chat_member)
async def clean_service(msg: Message):
    if is_supergroup(msg.chat.id):
        await msg.delete()

# Админ-команды: /ban, /mute и т.д.
@dp.message(Command(commands=["ban", "unban", "mute", "unmute"]))
async def admin_commands(msg: Message):
    if not msg.reply_to_message or not is_supergroup(msg.chat.id):
        await msg.delete()
        return

    if not await is_admin_or_owner(msg.chat.id, msg.from_user.id):
        await msg.delete()
        return

    target = msg.reply_to_message.from_user
    if target.id == 7134895036:
        return await msg.reply("❌ You cannot use this command on the owner!")

    args = msg.text.split()
    duration = None
    if len(args) > 1 and args[1].isdigit():
        duration = int(args[1])

    end_time = datetime.now(timezone.utc) + timedelta(seconds=duration) if duration else datetime.now(timezone.utc) + timedelta(days=365*100)

    try:
        if msg.text.startswith("/ban"):
            await bot.ban_chat_member(msg.chat.id, target.id, until_date=int(end_time.timestamp()) if duration else None)
            await msg.reply(f"Banned {target.first_name} {'на ' + str(duration) + ' сек' if duration else 'навсегда'}.")
            if duration: add_timer("ban", msg.chat.id, target.id, end_time)

        elif msg.text.startswith("/unban"):
            await bot.unban_chat_member(msg.chat.id, target.id)
            remove_timer("ban", msg.chat.id, target.id)
            await msg.reply(f"Unbanned {target.first_name}")

        elif msg.text.startswith("/mute"):
            await bot.restrict_chat_member(
                msg.chat.id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(end_time.timestamp()) if duration else None
            )
            await msg.reply(f"Muted {target.first_name} {'на ' + str(duration) + ' сек' if duration else 'навсегда'}.")
            if duration: add_timer("mute", msg.chat.id, target.id, end_time)

        elif msg.text.startswith("/unmute"):
            await safe_unmute(msg.chat.id, target.id, target.first_name)
            remove_timer("mute", msg.chat.id, target.id)

    except Exception as e:
        await msg.reply(f"Ошибка: {e}")

# =================== Основные команды ===================
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    if len(msg.text.split()) > 1:
        await msg.delete()
        return
    await msg.answer(
        "*Available Commands:*\n\n"
        "/help — list of all available commands\n"
        "/rules — show the group rules\n"
        "/lesson_schedule — English lesson schedule\n"
        "/speaking_homework — current Speaking homework\n"
        "/grammar_homework — current Grammar homework\n"
        "/translate <word> — translate word\n\n"
        "Adding any text after a command → message will be deleted."
        parse_mode="Markdown"
    )

@dp.message(Command("rules"))
async def cmd_rules(msg: Message):
    if len(msg.text.split()) > 1: await msg.delete(); return
    await msg.answer(
        "📜 *Group Rules*\n\n"
        "1️⃣ *Be respectful* — Treat everyone with kindness. No insults, bad words, hate speech, or harassment.\n\n"
        "2️⃣ *No bullying* — Any form of bullying, mocking, or targeting other members is strictly forbidden.\n\n"
        "3️⃣ *No politics, religion, nationality, or student-related discussions* — Focus on learning English.\n\n"
        "4️⃣ *Follow the rules* — If you break any rule, your message will be deleted by me or an admin.\n\n"
        "5⃣ *Rules may change* — Admins can update or add new rules at any time."
        parse_mode="Markdown"
    )

@dp.message(Command("lesson_schedule"))
async def cmd_schedule(msg: Message):
    if len(msg.text.split()) > 1: await msg.delete(); return
    await msg.answer(
        "*Расписание занятий*\n\n"
        "*Speaking*\n"
        "• Понедельник\n"
        "• Среда\n"
        "• Пятница\n\n"
        "*Grammar*\n"
        "• Вторник\n"
        "• Четверг",
        parse_mode="Markdown"
    )

@dp.message(Command("speaking_homework"))
async def cmd_speaking(msg: Message):
    if len(msg.text.split()) > 1: await msg.delete(); return

    photo_paths = [
        "/storage/emulated/0/DCIM/Альбом 1/Words(1).jpg",
        "/storage/emulated/0/DCIM/Альбом 1/Words(2).jpg"
    ]
    media = []
    for i, path in enumerate(photo_paths):
        if os.path.exists(path):
            if i == 0:
                media.append(InputMediaPhoto(
                    media=InputFile(path),
                    caption="*Speaking Homework*\n\nУчи только значение слов",
                    parse_mode="Markdown"
                ))
            else:
                media.append(InputMediaPhoto(media=InputFile(path)))
    
    if media:
        await msg.answer_media_group(media)
    else:
        await msg.answer("Фото Speaking ДЗ не найдены")

@dp.message(Command("grammar_homework"))
async def cmd_grammar(msg: Message):
    if len(msg.text.split()) > 1: await msg.delete(); return
    await msg.answer(
        "*Grammar Homework*\n\n"
        "Все упражнения из unit 13 и 14",
        parse_mode="Markdown"
    )

@dp.message(Command("translate"))
async def cmd_translate(msg: Message):
    text = msg.text[len("/translate"):].strip()
    if not text or " " in text:
        await msg.delete()
        return

    loop = asyncio.get_running_loop()
    try:
        detected = await loop.run_in_executor(None, translator.detect, text)
        dest = "en" if detected.lang in ["ru", "tg", "tajik"] else "ru"
        translated = await loop.run_in_executor(None, translator.translate, text, dest=dest)
        await msg.reply(
            f"*Оригинал* ({detected.lang.upper()}): {text}\n"
            f"*Перевод* ({dest.upper()}): {translated.text}",
            parse_mode="Markdown"
        )
    except:
        await msg.reply("Ошибка перевода")

# =================== Запуск ===================
async def on_startup():
    print("Бот запущен и готов к работе!")

async def on_shutdown():
    for task in tasks.values():
        task.cancel()
    await bot.session.close()

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
