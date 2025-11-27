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
    MessageEntity,
)
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

# Optional sync libs used in executor
from googletrans import Translator
from spellchecker import SpellChecker

# =================== Config ===================
OWNER_ID = 7134895036  # Твой Telegram ID
BOT_TOKEN = "8232627546:AAHfb6P_BwQ8lJbhaKH7OkK_sCkNFlBgPD8"
TIMERS_FILE = "timers.json"

# =================== Init bot & dp ===================
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

translator = Translator()
spell = SpellChecker(language="en")

SHORT_WORDS = {"i", "a", "an", "to", "in", "on", "at", "of", "is", "am", "are", "be", "do", "go"}

# =================== Utilities ===================
def is_english(text: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9\s\.,!?'\-:;@#\$%\^&\*]+", text.strip()))

def is_supergroup(chat_id: int) -> bool:
    # same heuristic as before
    return chat_id < -1000000000000

# =================== Timers storage & scheduler ===================
# Data format:
# {
#   "mute": {"<chat>-<user>": "<ISO time>"},
#   "ban": {"<chat>-<user>": "<ISO time>"}
# }
timers: Dict[str, Dict[str, str]] = {"mute": {}, "ban": {}}
tasks: Dict[str, asyncio.Task] = {}  # running asyncio tasks for scheduled finish

def load_timers():
    global timers
    if not os.path.exists(TIMERS_FILE):
        timers = {"mute": {}, "ban": {}}
        return
    try:
        with open(TIMERS_FILE, "r", encoding="utf-8") as f:
            timers = json.load(f)
            if "mute" not in timers: timers["mute"] = {}
            if "ban" not in timers: timers["ban"] = {}
    except Exception as e:
        print(f"[!] Failed to load timers file: {e}")
        timers = {"mute": {}, "ban": {}}

def save_timers():
    try:
        with open(TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(timers, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Failed to save timers: {e}")

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
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        try:
            await bot.send_message(chat_id, f"♻️ {name} has been unmuted automatically.")
        except Exception:
            pass
    except Exception:
        pass

async def safe_unban(chat_id: int, user_id: int, name: str = "User"):
    try:
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        try:
            await bot.send_message(chat_id, f"♻️ {name} has been unbanned automatically.")
        except Exception:
            pass
    except Exception:
        pass

def schedule_task_name(timer_type: str, chat_id: int, user_id: int) -> str:
    return f"{timer_type}:{chat_id}:{user_id}"

def add_timer(timer_type: str, chat_id: int, user_id: int, end_time: datetime):
    k = key_for(chat_id, user_id)
    timers[timer_type][k] = end_time.isoformat()
    save_timers()
    # create and store task
    task_name = schedule_task_name(timer_type, chat_id, user_id)
    if task_name in tasks:
        # cancel existing
        t = tasks.pop(task_name)
        t.cancel()
    tasks[task_name] = asyncio.create_task(_timer_task(timer_type, chat_id, user_id, end_time))

def remove_timer(timer_type: str, chat_id: int, user_id: int):
    k = key_for(chat_id, user_id)
    if k in timers.get(timer_type, {}):
        timers[timer_type].pop(k, None)
        save_timers()
    task_name = schedule_task_name(timer_type, chat_id, user_id)
    if task_name in tasks:
        t = tasks.pop(task_name)
        t.cancel()

async def _timer_task(timer_type: str, chat_id: int, user_id: int, end_time: datetime):
    try:
        now = datetime.now(timezone.utc)
        remaining = (end_time - now).total_seconds()
        if remaining <= 0:
            remaining = 1
        await asyncio.sleep(remaining)
        # call finish
        if timer_type == "mute":
            await safe_unmute(chat_id, user_id)
        elif timer_type == "ban":
            await safe_unban(chat_id, user_id)
        remove_timer(timer_type, chat_id, user_id)
    except asyncio.CancelledError:
        return
    except Exception as e:
        print(f"[!] Timer task error ({timer_type}, {chat_id}, {user_id}): {e}")

def restore_timers():
    now = datetime.now(timezone.utc)
    for timer_type in ["mute", "ban"]:
        keys_to_remove = []
        for key, iso_time in list(timers[timer_type].items()):
            try:
                parts = key.split("-")
                if len(parts) != 2:
                    keys_to_remove.append(key)
                    continue
                chat_id, user_id = map(int, parts)
                end_time = datetime.fromisoformat(iso_time)
                # schedule
                add_timer(timer_type, chat_id, user_id, end_time)
            except Exception as e:
                print(f"❌ Failed to restore {timer_type} timer for key '{key}': {e}")
                keys_to_remove.append(key)
        for key in keys_to_remove:
            timers[timer_type].pop(key, None)
    save_timers()

# Load timers at startup
load_timers()
restore_timers()

# =================== Handlers ===================

@dp.message(F.content_type.in_({"new_chat_members", "left_chat_member"}))
async def handle_join_leave(msg: Message):
    # if supergroup - try delete join/leave message to keep chat clean
    if is_supergroup(msg.chat.id):
        try:
        except Exception:
            pass
    else:
        if msg.content_type == "new_chat_members":
            for user in msg.new_chat_members:
                try:
                    await msg.reply(f"Welcome, {user.first_name}!")
                    await msg.delete()
                except Exception:
                    pass

# Helper: check if executor (sender) is owner or admin
async def is_sender_admin_or_owner(chat_id: int, user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.is_chat_admin()
    except Exception:
        return False

@dp.message(F.text.startswith(("/ban", "/unban", "/mute", "/unmute")))
async def handle_admin_commands(msg: Message):
    # require reply
    if not msg.reply_to_message:
        # delete the command for cleanliness
        try:
            await msg.delete()
        except Exception:
            pass
        return

    target = msg.reply_to_message.from_user

    # Check admin / owner
    is_admin = await is_sender_admin_or_owner(msg.chat.id, msg.from_user.id)
    if not is_admin:
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # protect bot owner
    if target.id == 7134895036:
        await msg.reply("❌ You cannot use this command on the owner!")
        return

    # only for supergroups
    if not is_supergroup(msg.chat.id):
        await msg.reply("⚠️ This feature is available only in supergroups.")
        return

    parts = msg.text.split()
    duration = None
    if len(parts) > 1:
        if parts[1].isdigit():
            duration = int(parts[1])
        else:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # compute end_time; if no duration we use a very large time (practically permanent)
    if duration:
        end_time = datetime.now(timezone.utc) + timedelta(seconds=duration)
    else:
        # 100 years in future as "permanent"
        end_time = datetime.now(timezone.utc) + timedelta(days=365*100)

    try:
        if msg.text.startswith('/ban'):
            await bot.ban_chat_member(chat_id=msg.chat.id, user_id=target.id)
            await msg.reply(f"✅ {target.first_name} has been banned{' for ' + str(duration) + ' seconds' if duration else ''}.")
            if duration:
                add_timer("ban", msg.chat.id, target.id, end_time)

        elif msg.text.startswith('/unban'):
            await bot.unban_chat_member(chat_id=msg.chat.id, user_id=target.id)
            remove_timer("ban", msg.chat.id, target.id)
            await msg.reply(f"✅ {target.first_name} has been unbanned.")

        elif msg.text.startswith('/mute'):
            # Restrict sending messages
            await bot.restrict_chat_member(
                chat_id=msg.chat.id,
                user_id=target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(end_time.timestamp()),
            )
            await msg.reply(f"✅ {target.first_name} has been muted{' for ' + str(duration) + ' seconds' if duration else ''}.")
            if duration:
                add_timer("mute", msg.chat.id, target.id, end_time)

        elif msg.text.startswith('/unmute'):
            await safe_unmute(msg.chat.id, target.id, target.first_name)
            remove_timer("mute", msg.chat.id, target.id)

    except TelegramBadRequest as e:
        await msg.reply(f"❌ Error: {e}")
    except TelegramAPIError as e:
        await msg.reply(f"❌ Telegram API error: {e}")
    except Exception as e:
        await msg.reply(f"❌ Error while executing the command: {e}")

# =================== lesson_schedule, rules, help ===================
@dp.message(F.text == "/lesson_schedule")
async def lesson_schedule(msg: Message):
    # if text has extra content, delete and optionally change karma (your logic referenced change_karma earlier)
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) > 1:
        try:
            await msg.delete()
        except Exception:
            pass
        # placeholder for change_karma(user_id, -1) if you implement it
        return

    schedule_text = (
        "📚 *Lesson Schedule*\n\n"
        "🗣️ *Speaking*\n"
        "> Monday\n"
        "> Wednesday\n"
        "> Friday\n\n"
        "📘 *Grammar*\n"
        "> Tuesday\n"
        "> Thursday"
    )
    await bot.send_message(msg.chat.id, schedule_text, parse_mode="Markdown")

@dp.message(F.text == "/rules")
async def rules_command(msg: Message):
    # if user added extra text - delete
    text_after = msg.text.replace('/rules', '', 1).strip()
    if text_after != '':
        try:
            await msg.delete()
        except Exception:
            pass
        return

    rules_text = (
        "📜 *Group Rules*\n\n"
        "1️⃣ *Be respectful* — Treat everyone with kindness. No insults, bad words, hate speech, or harassment.\n\n"
        "2️⃣ *No bullying* — Any form of bullying, mocking, or targeting other members is strictly forbidden.\n\n"
        "3️⃣ *No politics, religion, nationality, or student-related discussions* — Focus on learning English.\n\n"
        "4️⃣ *Follow the rules* — If you break any rule, your message will be deleted by me or an admin.\n\n"
        "5⃣ *Rules may change* — Admins can update or add new rules at any time."
    )
    await bot.send_message(msg.chat.id, rules_text, parse_mode="Markdown")

@dp.message(F.text == "/help")
async def help_command(msg: Message):
    command_text = msg.text.split()[0]
    if msg.text.strip() != command_text:
        try:
            await msg.delete()
        except:
            pass
        return

    help_text = (
        "*Available Commands:*\n\n"
        "/help — list of all available commands\n"
        "/rules — show the group rules\n"
        "/lesson_schedule — English lesson schedule\n"
        "/speaking_homework — current Speaking homework\n"
        "/grammar_homework — current Grammar homework\n"
        "/translate <word> — translate word\n\n"
        "Adding any text after a command → message will be deleted."
    )
    await msg.answer(help_text, parse_mode="Markdown")
# =================== Speaking and Grammar Homework ===================
@dp.message(F.text == "/speaking_homework")
async def speaking_homework(msg: Message):
    try:
        photo_paths = [
            "/storage/emulated/0/DCIM/Альбом 1/Words(1).jpg",
            "/storage/emulated/0/DCIM/Альбом 1/Words(2).jpg"
        ]
        media = []
        for i, path in enumerate(photo_paths):
            if not os.path.exists(path):
                continue
            if i == 0:
                media.append(InputMediaPhoto(media=InputFile(path), caption="🗣 *Speaking Homework*\n\n🎧 Learn only meaning", parse_mode="Markdown"))
            else:
                media.append(InputMediaPhoto(media=InputFile(path)))
        if media:
            await bot.send_media_group(msg.chat.id, media=media)
        else:
            await bot.send_message(msg.chat.id, "❌ Speaking homework photos not found on server.")
    except Exception as e:
        print(f"Error sending speaking homework: {e}")

@dp.message(F.text == "/grammar_homework")
async def grammar_homework(msg: Message):
    # ensure exact command
    if msg.text.strip() != "/grammar_homework":
        try:
            await msg.delete()
        except Exception:
            pass
        return

    try:
        homework_text = (
            "📘 *Grammar Homework*\n\n"
            "✏️ All exercises from unit 13 and 14"
        )
        await bot.send_message(msg.chat.id, homework_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending grammar homework: {e}")

# =================== Translate Command ===================
@dp.message(F.text.startswith("/translate"))
async def translate_word(msg: Message):
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await bot.send_message(msg.chat.id, "❌ Please provide a single word to translate. Example: /translate привет или hello")
        return

    text_to_translate = parts[1].strip()
    import re
    if len(text_to_translate.split()) > 1 or not re.fullmatch(r"[A-Za-zА-Яа-яЁёЇїІіѢѣҶҷҲҳҚқҒғЪъ]+", text_to_translate):
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # googletrans is synchronous; run in executor
    loop = asyncio.get_running_loop()
    try:
        detected = await loop.run_in_executor(None, partial(translator.detect, text_to_translate))
        src_lang = detected.lang
        dest_lang = "en" if src_lang in ["ru", "tg"] else "ru"
        translated = await loop.run_in_executor(None, partial(translator.translate, text_to_translate, dest=dest_lang))
        await msg.reply(
            f"🌐 Original ({src_lang.upper()}): {text_to_translate}\n"
            f"➡️ Translation ({dest_lang.upper()}): {translated.text}"
        )
    except Exception as e:
        await msg.reply(f"❌ Error while translating: {e}")

# =================== Startup / Shutdown ===================
async def on_startup():
    print("Aiogram bot started")
    # timers already restored on import/load; ensure tasks exist (restore_timers already created tasks)
    # nothing else needed now

async def on_shutdown():
    # cancel scheduled tasks gracefully
    for t in list(tasks.values()):
        t.cancel()
    await bot.session.close()

# ================ Run ================
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown))
    except KeyboardInterrupt:
        print("Bot stopped by user")
