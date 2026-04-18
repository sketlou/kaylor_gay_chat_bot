import asyncio
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    InputMediaPhoto,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
CHANNEL_ID = os.getenv("CHANNEL_ID")

YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@Kaylor5rp"
LAST_VIDEO_URL = "https://youtu.be/EYmKJhSDIgg?si=MOO0dvzvPCWCirj5"

COMMON_GIF_PATH = "instruction.gif.mp4"
DATA_FILE = "giveaways.json"
ADMIN_IDS = {5034940986, 570922520, 448964986}

VERIFICATION_HOURS = 72
SCREENSHOT_COLLECT_SECONDS = 60

VERIFICATION_ACCEPT_TEXT = (
    "✅ Скриншоты получены.\n\n"
    "Заявка принята и будет отправлена на проверку.\n"
    "Если нужно, можешь прикрепить еще скриншоты в течение минуты."
)

REDUXES = {
    "afterlight": {
        "title": "Afterlight",
        "button_text": "Afterlight",
        "review_video_link": "https://youtu.be/9Dx4QmYxntY?si=WjI-ru8NWjLWnssO",
        "delivery_text": (
            "Afterlight\n\n"
            "☝️ Просьба, никому не сливать и не кидать попрошайкам, буду очень тебе благодарен, заранее спасибо тебе 🥰\n"
            "❗️ИЗ АРХИВА НУЖНО ПЕРЕКИНУТЬ ВСЮ ПАПКУ UPDATE В КОРНЕВУЮ ПАПКУ ИГРЫ ❗️\n\n"
            "Ссылка на скачивание:\n"
            "https://drive.google.com/file/d/1Zx03juaswcNvtItrsk3SA7kJVWr0qOQQ/view?usp=sharing"
        ),
    },
    "rp redux": {
        "title": "RP Redux",
        "button_text": "RP Redux",
        "review_video_link": "https://youtu.be/EYmKJhSDIgg?si=MOO0dvzvPCWCirj5",
        "delivery_text": (
            "RP Redux\n\n"
            "☝️ Просьба, никому не сливать и не кидать попрошайкам, буду очень тебе благодарен, заранее спасибо тебе 🥰\n"
            "❗️ИЗ АРХИВА НУЖНО ПЕРЕКИНУТЬ ВСЮ ПАПКУ UPDATE В КОРНЕВУЮ ПАПКУ ИГРЫ ❗️\n\n"
            "Ссылка на скачивание:\n"
            "https://drive.google.com/file/d/1CEkL4ol7PzXbs4-MDYKKSg40E4I9TR_v/view?usp=sharing"
        ),
    },
}

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

pending_reject_reasons = {}
admin_request_message_meta = {}

# Буфер скриншотов по пользователю
verification_photo_buffer = defaultdict(list)
verification_collect_tasks = {}
verification_ack_sent = set()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_data_file():
    path = Path(DATA_FILE)
    if not path.exists():
        path.write_text(
            json.dumps(
                {
                    "giveaways": {},
                    "users": {},
                    "banned_users": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def migrate_data(data: dict) -> dict:
    if "giveaways" not in data or not isinstance(data["giveaways"], dict):
        data["giveaways"] = {}

    if "users" not in data or not isinstance(data["users"], dict):
        data["users"] = {}

    if "banned_users" not in data or not isinstance(data["banned_users"], dict):
        data["banned_users"] = {}

    for giveaway_id, giveaway in data["giveaways"].items():
        giveaway.setdefault("title", f"Розыгрыш {giveaway_id}")
        giveaway.setdefault("description", "")
        if "participants" not in giveaway or not isinstance(giveaway["participants"], list):
            giveaway["participants"] = []
        giveaway.setdefault("is_active", True)
        giveaway.setdefault("winner", None)
        giveaway.setdefault("posted_message_id", None)
        giveaway.setdefault("posted_chat_id", None)
        giveaway.setdefault("result_posted_message_id", None)
        giveaway.setdefault("result_posted_chat_id", None)

        normalized = []
        for participant in giveaway["participants"]:
            if not isinstance(participant, dict):
                continue
            normalized.append(
                {
                    "user_id": participant.get("user_id"),
                    "username": participant.get("username"),
                    "full_name": participant.get("full_name") or participant.get("username") or "Без имени",
                }
            )
        giveaway["participants"] = normalized

    for _, user_data in data["users"].items():
        user_data.setdefault("verified_until", None)
        user_data.setdefault("verification_pending", False)
        user_data.setdefault("verification_collecting", False)

    return data


def load_data() -> dict:
    ensure_data_file()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return migrate_data(data)


def save_data(data: dict):
    data = migrate_data(data)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_user_record(data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "verified_until": None,
            "verification_pending": False,
            "verification_collecting": False,
        }
    return data["users"][uid]


def is_user_banned(data: dict, user_id: int) -> bool:
    return str(user_id) in data.get("banned_users", {})


def get_user_ban_reason(data: dict, user_id: int) -> str:
    item = data.get("banned_users", {}).get(str(user_id))
    if not item:
        return ""
    return item.get("reason", "")


def is_user_verified_now(data: dict, user_id: int) -> bool:
    user = get_user_record(data, user_id)
    verified_until = user.get("verified_until")
    if not verified_until:
        return False

    try:
        expires_at = datetime.fromisoformat(verified_until)
    except Exception:
        return False

    return now_utc() < expires_at


def get_verified_until(data: dict, user_id: int):
    user = get_user_record(data, user_id)
    verified_until = user.get("verified_until")
    if not verified_until:
        return None
    try:
        return datetime.fromisoformat(verified_until)
    except Exception:
        return None


def set_user_verified_for_hours(data: dict, user_id: int, hours: int):
    user = get_user_record(data, user_id)
    user["verified_until"] = (now_utc() + timedelta(hours=hours)).isoformat()
    user["verification_pending"] = False
    user["verification_collecting"] = False


def set_verification_pending(data: dict, user_id: int, value: bool):
    user = get_user_record(data, user_id)
    user["verification_pending"] = value


def is_verification_pending(data: dict, user_id: int) -> bool:
    user = get_user_record(data, user_id)
    return bool(user.get("verification_pending", False))


def set_verification_collecting(data: dict, user_id: int, value: bool):
    user = get_user_record(data, user_id)
    user["verification_collecting"] = value


def is_verification_collecting(data: dict, user_id: int) -> bool:
    user = get_user_record(data, user_id)
    return bool(user.get("verification_collecting", False))


def get_redux_by_button(button_text: str):
    for key, value in REDUXES.items():
        if value["button_text"] == button_text:
            return key, value
    return None, None


def build_main_kb():
    rows = [[KeyboardButton(text=value["button_text"])] for value in REDUXES.values()]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def build_admin_kb(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Одобрить", callback_data=f"approve_verification:{user_id}")],
            [InlineKeyboardButton(text="Отклонить", callback_data=f"reject_verification:{user_id}")],
        ]
    )


def build_giveaway_join_kb(giveaway_id: str):
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id, {})
    count = len(giveaway.get("participants", []))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Участвовать ({count})", callback_data=f"join_giveaway:{giveaway_id}")]
        ]
    )


def build_giveaway_preview_kb(giveaway_id: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Опубликовать в канал", callback_data=f"publish_giveaway:{giveaway_id}")]
        ]
    )


def build_giveaway_result_preview_kb(giveaway_id: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Опубликовать итоги в канал", callback_data=f"publish_result:{giveaway_id}")]
        ]
    )


def format_giveaway_text(giveaway_id: str, giveaway: dict) -> str:
    text = f"🎉 <b>{giveaway['title']}</b>\n\n"
    if giveaway.get("description"):
        text += f"{giveaway['description']}\n\n"
    text += (
        "Нажми кнопку ниже, чтобы участвовать.\n"
        "Условие: быть подписанным на этот канал"
    )
    return text


def format_giveaway_result_text(giveaway_id: str, giveaway: dict) -> str:
    winner = giveaway.get("winner")
    if not winner:
        return f"Итоги розыгрыша <b>{giveaway['title']}</b> пока не определены."

    winner_username = winner.get("username")
    winner_full_name = winner.get("full_name", "Победитель")
    winner_display = f"@{winner_username}" if winner_username else winner_full_name

    return (
        f"🏆 <b>Итоги розыгрыша</b>\n\n"
        f"🎉 <b>{giveaway['title']}</b>\n\n"
        f"Победитель: {winner_display}\n"
        f"User ID: <code>{winner['user_id']}</code>"
    )


def format_verification_request_text(user_id: int, username: str) -> str:
    username_text = f"@{username}" if username else "без username"
    return (
        "<b>Новая заявка на верификацию</b>\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Username: {username_text}"
    )


async def send_redux_to_user(user_id: int, redux_key: str) -> bool:
    redux_data = REDUXES.get(redux_key)
    if not redux_data:
        return False

    caption = redux_data["delivery_text"]

    try:
        if Path(COMMON_GIF_PATH).exists():
            await bot.send_animation(
                chat_id=user_id,
                animation=FSInputFile(COMMON_GIF_PATH),
                caption=caption,
            )
        else:
            await bot.send_message(chat_id=user_id, text=caption)
        return True
    except Exception as e:
        logging.error(f"Ошибка отправки редукса пользователю {user_id}: {e}")
        return False


async def mark_admin_request_rejected(source_chat_id: int, source_message_id: int, reason_text: str):
    meta = admin_request_message_meta.get((source_chat_id, source_message_id))

    if not meta:
        try:
            await bot.edit_message_reply_markup(
                chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=None,
            )
        except Exception as e:
            logging.warning(f"Не удалось убрать кнопки у заявки: {e}")
        return

    new_text = meta["base_text"] + f"\n\n❌ Отклонено.\nПричина: {reason_text}"

    try:
        if meta["type"] == "photo":
            await bot.edit_message_caption(
                chat_id=source_chat_id,
                message_id=source_message_id,
                caption=new_text,
                reply_markup=None,
            )
        else:
            await bot.edit_message_text(
                chat_id=source_chat_id,
                message_id=source_message_id,
                text=new_text,
                reply_markup=None,
            )
    except Exception as e:
        logging.warning(f"Не удалось обновить сообщение заявки: {e}")
        try:
            await bot.edit_message_reply_markup(
                chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=None,
            )
        except Exception as inner_e:
            logging.warning(f"Не удалось убрать кнопки у заявки: {inner_e}")

async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }
    except Exception as e:
        logging.warning(f"Не удалось проверить подписку: {e}")
        return False

async def finish_admin_request_message(callback: CallbackQuery, status_text: str):
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "Заявка") + status_text,
                reply_markup=None,
            )
        else:
            await callback.message.edit_text(
                (callback.message.text or "Заявка") + status_text,
                reply_markup=None,
            )
    except Exception as e:
        logging.error(f"Ошибка обновления сообщения заявки: {e}")


async def send_start_text(message: Message, data: dict):
    if is_user_banned(data, message.from_user.id):
        reason = get_user_ban_reason(data, message.from_user.id)
        text = "Ты не можешь пользоваться ботом."
        if reason:
            text += f"\nПричина: {reason}"
        await message.answer(text)
        return

    if is_user_verified_now(data, message.from_user.id):
        expires_at = get_verified_until(data, message.from_user.id)
        expires_text = expires_at.strftime("%d.%m.%Y %H:%M UTC") if expires_at else "неизвестно"

        await message.answer(
            "Привет.\n\n"
            "Верификация пройдена ✅\n"
            "Теперь ты можешь выбрать нужный редукс кнопкой ниже.",
            reply_markup=build_main_kb(),
        )
        return

    await message.answer(
        "Привет.\n\n"
        "Для доступа к редуксам необходимо пройти верификацию.\n\n"
        "Как пройти верификацию:\n\n"
        f"1) подпишись на YouTube-канал ({YOUTUBE_CHANNEL_URL})\n"
        f"2) поставь лайк под последним видео ({LAST_VIDEO_URL})\n\n"
        "3) отправь скриншоты подтверждения в этот чат"
    )


async def flush_verification_photos(user_id: int):
    await asyncio.sleep(SCREENSHOT_COLLECT_SECONDS)

    data = load_data()

    try:
        photos = verification_photo_buffer.get(user_id, [])
        if not photos:
            return

        if is_user_banned(data, user_id) or is_user_verified_now(data, user_id):
            return

        if is_verification_pending(data, user_id):
            return

        first_msg = photos[0]
        username = first_msg.from_user.username or ""
        base_text = format_verification_request_text(user_id=user_id, username=username)
        kb = build_admin_kb(user_id=user_id)

        media = []
        for idx, msg in enumerate(photos):
            photo = msg.photo[-1].file_id
            if idx == 0:
                media.append(InputMediaPhoto(media=photo, caption=base_text, parse_mode=ParseMode.HTML))
            else:
                media.append(InputMediaPhoto(media=photo))

        if len(media) == 1:
            sent = await bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photos[0].photo[-1].file_id,
                caption=base_text,
                reply_markup=kb,
            )
            admin_request_message_meta[(sent.chat.id, sent.message_id)] = {
                "type": "photo",
                "base_text": base_text,
            }
        else:
            sent_messages = await bot.send_media_group(chat_id=ADMIN_CHAT_ID, media=media)
            last_message_id = sent_messages[-1].message_id

            action_message = await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=base_text,
                reply_markup=kb,
                reply_to_message_id=last_message_id,
            )

            admin_request_message_meta[(action_message.chat.id, action_message.message_id)] = {
                "type": "text",
                "base_text": base_text,
            }

        set_verification_pending(data, user_id, True)
        set_verification_collecting(data, user_id, False)
        save_data(data)
    except Exception as e:
        logging.error(f"Ошибка отправки заявки на верификацию для {user_id}: {e}")
    finally:
        verification_photo_buffer.pop(user_id, None)
        verification_collect_tasks.pop(user_id, None)
        verification_ack_sent.discard(user_id)


@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    data = load_data()
    await send_start_text(message, data)


@dp.message(Command("help"), F.chat.type == "private")
async def help_handler(message: Message):
    text = (
        "<b>Доступные команды:</b>\n"
        "/help\n"
        "/chatid\n"
        "/myid"
    )

    if is_admin(message.from_user.id):
        text += (
            "\n\n<b>Админ-команды:</b>\n"
            "/giveaway_create ID Название | Описание - создать розыгрыш\n"
            "/giveaway_preview ID - показать предпросмотр розыгрыша\n"
            "/giveaway_post ID - сразу опубликовать розыгрыш в канал\n"
            "/giveaway_refresh ID - обновить кнопку участников у опубликованного розыгрыша\n"
            "/giveaway_list - список всех розыгрышей\n"
            "/giveaway_members ID - участники конкретного розыгрыша\n"
            "/giveaway_pick ID - выбрать победителя и показать предпросмотр итогов\n"
            "/giveaway_result_post ID - сразу опубликовать итоги в канал\n"
            "/giveaway_reroll ID - перевыбрать победителя\n"
            "/ban USER_ID [причина] - заблокировать пользователя\n"
            "/unban USER_ID - снять блокировку\n"
            "/verified USER_ID - проверить срок верификации пользователя"
        )

    await message.answer(text)


@dp.message(Command("chatid"), F.chat.type == "private")
async def chatid_handler(message: Message):
    await message.answer(
        f"ID этого чата: <code>{message.chat.id}</code>\n"
        f"Тип чата: <code>{message.chat.type}</code>"
    )


@dp.message(Command("myid"), F.chat.type == "private")
async def myid_handler(message: Message):
    await message.answer(f"Твой user id: <code>{message.from_user.id}</code>")


@dp.message(Command("verified"), F.chat.type == "private")
async def verified_info_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/verified USER_ID")
        return

    target_user_id = parts[1].strip()
    data = load_data()
    user = data["users"].get(target_user_id)

    if not user or not user.get("verified_until"):
        await message.answer("У пользователя нет активной верификации.")
        return

    await message.answer(
        f"USER_ID: <code>{target_user_id}</code>\n"
        f"verified_until: <code>{user['verified_until']}</code>"
    )


@dp.message(Command("ban"), F.chat.type == "private")
async def ban_user_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 2)
    if len(parts) < 2:
        await message.answer("Использование:\n/ban USER_ID [причина]")
        return

    target_user_id = parts[1].strip()
    reason = parts[2].strip() if len(parts) > 2 else "Без причины"

    data = load_data()
    data["banned_users"][str(target_user_id)] = {
        "reason": reason,
        "banned_at": now_utc().isoformat(),
    }
    save_data(data)

    await message.answer(f"Пользователь <code>{target_user_id}</code> заблокирован.")


@dp.message(Command("unban"), F.chat.type == "private")
async def unban_user_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/unban USER_ID")
        return

    target_user_id = parts[1].strip()

    data = load_data()
    if str(target_user_id) in data["banned_users"]:
        del data["banned_users"][str(target_user_id)]
        save_data(data)
        await message.answer(f"Пользователь <code>{target_user_id}</code> разблокирован.")
    else:
        await message.answer("Пользователь не найден в бан-листе.")


@dp.message(Command("giveaway_create"), F.chat.type == "private")
async def giveaway_create_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer(
            "Использование:\n"
            "/giveaway_create ID Название | Описание\n\n"
            "Описание необязательно.\n"
            "Пример:\n"
            "/giveaway_create after1 Розыгрыш Afterlight | 1 победитель, итоги вечером"
        )
        return

    giveaway_id = parts[1].strip()
    rest = parts[2].strip()

    if "|" in rest:
        title, description = [x.strip() for x in rest.split("|", 1)]
    else:
        title = rest
        description = ""

    data = load_data()
    if giveaway_id in data["giveaways"]:
        await message.answer("Розыгрыш с таким ID уже существует.")
        return

    data["giveaways"][giveaway_id] = {
        "title": title,
        "description": description,
        "participants": [],
        "is_active": True,
        "winner": None,
        "posted_message_id": None,
        "posted_chat_id": None,
        "result_posted_message_id": None,
        "result_posted_chat_id": None,
    }
    save_data(data)

    await message.answer(
        f"Розыгрыш <b>{title}</b> создан.\n"
        f"ID: <code>{giveaway_id}</code>\n\n"
        f"Теперь можешь посмотреть его через /giveaway_preview {giveaway_id}"
    )


@dp.message(Command("giveaway_preview"), F.chat.type == "private")
async def giveaway_preview_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/giveaway_preview ID")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    if not giveaway["is_active"]:
        await message.answer("Этот розыгрыш уже завершен.")
        return

    text = format_giveaway_text(giveaway_id, giveaway)

    await message.answer(
        f"<b>Предпросмотр розыгрыша:</b>\n\n{text}",
        reply_markup=build_giveaway_preview_kb(giveaway_id),
    )


@dp.callback_query(F.data.startswith("publish_giveaway:"))
async def publish_giveaway_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    giveaway_id = callback.data.split(":", 1)[1]
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await callback.answer("Розыгрыш не найден.", show_alert=True)
        return

    if not giveaway["is_active"]:
        await callback.answer("Розыгрыш уже завершен.", show_alert=True)
        return

    text = format_giveaway_text(giveaway_id, giveaway)

    try:
        sent = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            reply_markup=build_giveaway_join_kb(giveaway_id),
        )
        giveaway["posted_message_id"] = sent.message_id
        giveaway["posted_chat_id"] = CHANNEL_ID
        save_data(data)

        await callback.answer("Опубликовано.")
        await callback.message.answer("Розыгрыш отправлен в основной канал.")
    except Exception as e:
        logging.error(f"Ошибка публикации розыгрыша: {e}")
        await callback.answer("Не удалось опубликовать розыгрыш.", show_alert=True)


@dp.message(Command("giveaway_post"), F.chat.type == "private")
async def giveaway_post_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/giveaway_post ID")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    if not giveaway["is_active"]:
        await message.answer("Этот розыгрыш уже завершен.")
        return

    text = format_giveaway_text(giveaway_id, giveaway)

    try:
        sent = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            reply_markup=build_giveaway_join_kb(giveaway_id),
        )
        giveaway["posted_message_id"] = sent.message_id
        giveaway["posted_chat_id"] = CHANNEL_ID
        save_data(data)

        await message.answer("Розыгрыш опубликован в канал.")
    except Exception as e:
        logging.error(f"Ошибка /giveaway_post: {e}")
        await message.answer("Не удалось опубликовать розыгрыш в канал.")


@dp.message(Command("giveaway_refresh"), F.chat.type == "private")
async def giveaway_refresh_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/giveaway_refresh ID")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    chat_id = giveaway.get("posted_chat_id")
    message_id = giveaway.get("posted_message_id")

    if not chat_id or not message_id:
        await message.answer("У этого розыгрыша нет данных о сообщении в канале.")
        return

    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=build_giveaway_join_kb(giveaway_id),
        )
        await message.answer("Счетчик обновлен.")
    except Exception as e:
        logging.error(f"Ошибка обновления розыгрыша: {e}")
        await message.answer("Не удалось обновить кнопку.")


@dp.message(Command("giveaway_list"), F.chat.type == "private")
async def giveaway_list_handler(message: Message):
    data = load_data()
    if not data["giveaways"]:
        await message.answer("Розыгрышей пока нет.")
        return

    lines = []
    for gid, g in data["giveaways"].items():
        status = "активен" if g["is_active"] else "завершен"
        lines.append(
            f"• <b>{g['title']}</b>\n"
            f"ID: <code>{gid}</code>\n"
            f"Статус: {status}\n"
            f"Участников: {len(g['participants'])}"
        )

    await message.answer("\n\n".join(lines))


@dp.message(Command("giveaway_members"), F.chat.type == "private")
async def giveaway_members_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/giveaway_members ID")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    if not giveaway["participants"]:
        await message.answer(f"В розыгрыше <b>{giveaway['title']}</b> пока нет участников.")
        return

    members = []
    for i, participant in enumerate(giveaway["participants"], start=1):
        username = participant.get("username")
        full_name = participant.get("full_name", "Без имени")
        user_id = participant.get("user_id")
        display = f"@{username}" if username else full_name
        members.append(f"{i}. {display} — <code>{user_id}</code>")

    await message.answer(
        f"<b>Участники розыгрыша {giveaway['title']}</b>\n"
        f"ID: <code>{giveaway_id}</code>\n"
        f"Всего: <b>{len(giveaway['participants'])}</b>\n\n"
        + "\n".join(members)
    )


@dp.message(Command("giveaway_pick"), F.chat.type == "private")
async def giveaway_pick_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n<code>/giveaway_pick ID</code>")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    if not giveaway["participants"]:
        await message.answer("В розыгрыше нет участников.")
        return

    if giveaway.get("winner"):
        text = format_giveaway_result_text(giveaway_id, giveaway)
        await message.answer(
            f"У этого розыгрыша уже выбран победитель.\n\n<b>Предпросмотр итогов:</b>\n\n{text}",
            reply_markup=build_giveaway_result_preview_kb(giveaway_id),
        )
        return

    winner = random.choice(giveaway["participants"])
    giveaway["winner"] = winner
    giveaway["is_active"] = False
    save_data(data)

    text = format_giveaway_result_text(giveaway_id, giveaway)

    await message.answer(
        f"Победитель выбран.\n\n<b>Предпросмотр итогов:</b>\n\n{text}",
        reply_markup=build_giveaway_result_preview_kb(giveaway_id),
    )

    posted_chat_id = giveaway.get("posted_chat_id")
    posted_message_id = giveaway.get("posted_message_id")
    if posted_chat_id and posted_message_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=posted_chat_id,
                message_id=posted_message_id,
                reply_markup=None,
            )
        except Exception as e:
            logging.warning(f"Не удалось убрать кнопку у завершенного розыгрыша: {e}")


@dp.message(Command("giveaway_result_post"), F.chat.type == "private")
async def giveaway_result_post_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/giveaway_result_post ID")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    if not giveaway.get("winner"):
        await message.answer("Сначала выбери победителя через /giveaway_pick ID")
        return

    text = format_giveaway_result_text(giveaway_id, giveaway)

    try:
        sent = await bot.send_message(chat_id=CHANNEL_ID, text=text)
        giveaway["result_posted_message_id"] = sent.message_id
        giveaway["result_posted_chat_id"] = CHANNEL_ID
        save_data(data)

        await message.answer("Итоги опубликованы в канал.")
    except Exception as e:
        logging.error(f"Ошибка публикации итогов: {e}")
        await message.answer("Не удалось опубликовать итоги в канал.")


@dp.callback_query(F.data.startswith("publish_result:"))
async def publish_result_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    giveaway_id = callback.data.split(":", 1)[1]
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await callback.answer("Розыгрыш не найден.", show_alert=True)
        return

    if not giveaway.get("winner"):
        await callback.answer("Сначала нужно выбрать победителя.", show_alert=True)
        return

    text = format_giveaway_result_text(giveaway_id, giveaway)

    try:
        sent = await bot.send_message(chat_id=CHANNEL_ID, text=text)
        giveaway["result_posted_message_id"] = sent.message_id
        giveaway["result_posted_chat_id"] = CHANNEL_ID
        save_data(data)

        await callback.answer("Итоги опубликованы.")
        await callback.message.answer("Итоги розыгрыша отправлены в основной канал.")
    except Exception as e:
        logging.error(f"Ошибка публикации итогов: {e}")
        await callback.answer("Не удалось опубликовать итоги.", show_alert=True)


@dp.message(Command("giveaway_reroll"), F.chat.type == "private")
async def giveaway_reroll_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование:\n/giveaway_reroll ID")
        return

    giveaway_id = parts[1].strip()
    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    participants = giveaway.get("participants", [])
    old_winner = giveaway.get("winner")

    if not participants:
        await message.answer("В розыгрыше нет участников.")
        return

    pool = participants
    if old_winner:
        pool = [p for p in participants if p["user_id"] != old_winner["user_id"]]

    if not pool:
        await message.answer("Нет другого участника для re-roll.")
        return

    new_winner = random.choice(pool)
    giveaway["winner"] = new_winner
    giveaway["is_active"] = False
    save_data(data)

    text = format_giveaway_result_text(giveaway_id, giveaway)
    await message.answer(
        f"🔁 Выполнен re-roll.\n\n<b>Предпросмотр новых итогов:</b>\n\n{text}",
        reply_markup=build_giveaway_result_preview_kb(giveaway_id),
    )


@dp.callback_query(F.data.startswith("join_giveaway:"))
async def join_giveaway_handler(callback: CallbackQuery):
    giveaway_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    data = load_data()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await callback.answer("Розыгрыш не найден.", show_alert=True)
        return

    if not giveaway["is_active"]:
        await callback.answer("Розыгрыш уже завершен.", show_alert=True)
        return

    for participant in giveaway["participants"]:
        if participant["user_id"] == user_id:
            await callback.answer("Ты уже участвуешь.", show_alert=True)
            return

    giveaway["participants"].append(
        {
            "user_id": user_id,
            "username": callback.from_user.username,
            "full_name": callback.from_user.full_name,
        }
    )
    save_data(data)

    try:
        await callback.message.edit_reply_markup(reply_markup=build_giveaway_join_kb(giveaway_id))
    except Exception as e:
        logging.warning(f"Не удалось обновить кнопку участников: {e}")

    await callback.answer("Ты участвуешь!", show_alert=True)


@dp.callback_query(F.data.startswith("approve_verification:"))
async def approve_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split(":", 1)[1])
    except Exception:
        await callback.answer("Некорректные данные кнопки", show_alert=True)
        return

    data = load_data()

    if is_user_banned(data, user_id):
        await callback.answer("Пользователь заблокирован.", show_alert=True)
        return

    try:
        set_user_verified_for_hours(data, user_id, VERIFICATION_HOURS)
        save_data(data)

        verification_photo_buffer.pop(user_id, None)
        task = verification_collect_tasks.pop(user_id, None)
        if task:
            task.cancel()
        verification_ack_sent.discard(user_id)

        await bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ Верификация пройдена.\n\n"
                f"Теперь в течение {VERIFICATION_HOURS} часов ты можешь получать редуксы без повторной проверки."
            ),
            reply_markup=build_main_kb(),
        )

        await finish_admin_request_message(
            callback,
            f"\n\n✅ Верификация одобрена. Пользователю открыт доступ на {VERIFICATION_HOURS} часа(ов).",
        )
        await callback.answer("Готово")
    except Exception as e:
        await callback.answer("Не удалось одобрить верификацию", show_alert=True)
        logging.error(f"Ошибка approve: {e}")


@dp.callback_query(F.data.startswith("reject_verification:"))
async def reject_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split(":", 1)[1])
    except Exception:
        await callback.answer("Некорректные данные кнопки", show_alert=True)
        return

    pending_reject_reasons[callback.from_user.id] = {
        "user_id": user_id,
        "source_chat_id": callback.message.chat.id,
        "source_message_id": callback.message.message_id,
    }

    await callback.answer()
    await callback.message.answer("Напиши причину отклонения для верификации одним сообщением.")


@dp.message(F.text)
async def text_router(message: Message):
    user_id = message.from_user.id

    if is_admin(user_id) and user_id in pending_reject_reasons:
        reject_text = (message.text or "").strip()

        if not reject_text:
            await message.answer("Пришли текст причины одним сообщением.")
            return

        if reject_text.startswith("/"):
            return

        pending = pending_reject_reasons[user_id]
        target_user_id = pending["user_id"]
        source_chat_id = pending["source_chat_id"]
        source_message_id = pending["source_message_id"]

        try:
            data = load_data()
            set_verification_pending(data, target_user_id, False)
            set_verification_collecting(data, target_user_id, False)
            save_data(data)

            verification_photo_buffer.pop(target_user_id, None)
            task = verification_collect_tasks.pop(target_user_id, None)
            if task:
                task.cancel()
            verification_ack_sent.discard(target_user_id)

            await bot.send_message(
                chat_id=target_user_id,
                text=f"Верификация отклонена -  {reject_text}",
            )

            await mark_admin_request_rejected(
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                reason_text=reject_text,
            )

            pending_reject_reasons.pop(user_id, None)
            await message.answer("Отклонение отправлено пользователю.")
        except Exception as e:
            logging.error(f"Ошибка при отклонении верификации: {e}")
            await message.answer("Не удалось отправить сообщение пользователю.")
        return

    if message.chat.type != "private":
        return

    data = load_data()

    if is_user_banned(data, user_id):
        reason = get_user_ban_reason(data, user_id)
        text = "Ты не можешь пользоваться ботом."
        if reason:
            text += f"\nПричина: {reason}"
        await message.answer(text)
        return

    redux_key, redux_data = get_redux_by_button(message.text)
    if redux_data:
        if is_user_verified_now(data, user_id):
            if not await check_subscription(user_id):
                await message.answer("Сначала подпишись на Telegram-канал.")
                return

            sent_ok = await send_redux_to_user(user_id, redux_key)
            if not sent_ok:
                await message.answer("При отправке редукса произошла ошибка.", reply_markup=build_main_kb())
            return

        await message.answer(
            "Сначала нужно пройти верификацию.\n\n"
            f"1) подпишись на YouTube-канал ({YOUTUBE_CHANNEL_URL})\n"
            f"2) поставь лайк под последним видео ({LAST_VIDEO_URL})\n\n"
            "3) отправь скриншоты подтверждения в этот чат"
        )
        return

    if is_user_verified_now(data, user_id):
        await message.answer(
            "Ты верифицирован. Выбери нужный редукс кнопкой ниже.",
            reply_markup=build_main_kb(),
        )
        return

    if is_verification_pending(data, user_id) or is_verification_collecting(data, user_id):
        await message.answer(
            "Сейчас от тебя ждут скриншоты для верификации.\n"
            "Отправь подтверждения сюда, и я передам заявку на проверку."
        )
        return

    await message.answer(
        "Сейчас от тебя ждут скриншоты для верификации.\n"
        "Отправь подтверждения сюда, и я передам заявку на проверку."
    )


@dp.message(F.photo, F.chat.type == "private")
async def photo_handler(message: Message):
    user_id = message.from_user.id
    data = load_data()

    if is_user_banned(data, user_id):
        await message.answer("Ты не можешь отправлять заявки.")
        return

    if is_user_verified_now(data, user_id):
        await message.answer(
            "Ты уже верифицирован. Повторная заявка не нужна.\n"
            "Выбирай редукс кнопкой ниже.",
            reply_markup=build_main_kb(),
        )
        return

    if is_verification_pending(data, user_id):
        await message.answer("Заявка на верификацию уже отправлена и ждет проверки.")
        return

    verification_photo_buffer[user_id].append(message)

    if user_id not in verification_ack_sent:
        await message.answer(VERIFICATION_ACCEPT_TEXT)
        verification_ack_sent.add(user_id)

    if not is_verification_collecting(data, user_id):
        set_verification_collecting(data, user_id, True)
        save_data(data)

    if user_id not in verification_collect_tasks:
        verification_collect_tasks[user_id] = asyncio.create_task(flush_verification_photos(user_id))


async def main():
    data = load_data()
    save_data(data)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
