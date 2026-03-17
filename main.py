import asyncio
import json
import logging
import random
import os
from collections import defaultdict
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

BOT_TOKEN = "8722873029:AAHkbZlZ_TNMa52YVjWZQyKW5pfgMGVn52Q"
ADMIN_CHAT_ID = -5164672894
CHANNEL_USERNAME = "@kaylor5rp"
CHANNEL_ID = -3434356931
COMMON_GIF_PATH = "instruction.gif.mp4"
GIVEAWAYS_FILE = "giveaways.json"
ADMIN_IDS = {5034940986, 570922520, 448964986}

REDUXES = {
    "afterlight": {
        "title": "Afterlight",
        "link": "https://drive.google.com/file/d/1Zx03juaswcNvtItrsk3SA7kJVWr0qOQQ/view?usp=sharing",
        "button_text": "Afterlight",
        "review_video_link": "https://youtu.be/9Dx4QmYxntY?si=WjI-ru8NWjLWnssO",
    },
    "rp redux":{
        "title":"RP Redux",
        "link":"https://drive.google.com/file/d/1CEkL4ol7PzXbs4-MDYKKSg40E4I9TR_v/view?usp=sharing",
        "button_text":"RP Redux",
        "review_video_link":"https://youtu.be/EYmKJhSDIgg",
    },
}

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_selected_redux = {}
media_group_buffer = defaultdict(list)
media_group_tasks = {}


def ensure_giveaways_file():
    path = Path(GIVEAWAYS_FILE)
    if not path.exists():
        path.write_text(json.dumps({"giveaways": {}}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_giveaways():
    ensure_giveaways_file()
    with open(GIVEAWAYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_giveaways(data):
    with open(GIVEAWAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_main_kb():
    rows = [[KeyboardButton(text=v["button_text"])] for v in REDUXES.values()]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def build_admin_kb(user_id: int, redux_key: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить ссылку", callback_data=f"approve:{redux_key}:{user_id}")],
        [InlineKeyboardButton(text="Отклонить", callback_data=f"reject:{redux_key}:{user_id}")]
    ])


def build_giveaway_join_kb(giveaway_id: str):
    data = load_giveaways()
    giveaway = data["giveaways"].get(giveaway_id, {})
    count = len(giveaway.get("participants", []))

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Участвовать ({count})", callback_data=f"join_giveaway:{giveaway_id}")],

    ])


def build_giveaway_preview_kb(giveaway_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Опубликовать в канал", callback_data=f"publish_giveaway:{giveaway_id}")]
    ])


def get_redux_by_button(button_text: str):
    for k, v in REDUXES.items():
        if v["button_text"] == button_text:
            return k, v
    return None, None


def format_giveaway_text(giveaway_id: str, giveaway: dict) -> str:
    text = f"🎉 <b>{giveaway['title']}</b>\n\n"
    if giveaway.get("description"):
        text += f"{giveaway['description']}\n\n"
    text += (
        "Нажми кнопку ниже, чтобы участвовать.\n"
        f"Условие: быть подписанным на {CHANNEL_USERNAME}"
    )
    return text

async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        }
    except Exception as e:
        logging.warning(f"Не удалось проверить подписку: {e}")
        return False


@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    redux_list = "\n".join([f"• {v['title']}" for v in REDUXES.values()])
    await message.answer(
        "Привет.\n\n"
        "Доступные редуксы:\n"
        f"{redux_list}",
        reply_markup=build_main_kb()
    )


@dp.message(Command("help"), F.chat.type == "private")
async def help_handler(message: Message):

    if is_admin(message.from_user.id):
        text = (
            "\n\n<b>Админ-команды:</b>\n"
            "/giveaway_create ID Название | Описание - создать розыгрыш\n"
            "/giveaway_preview ID - показать предпросмотр розыгрыша в личке\n"
            "/giveaway_post ID - сразу опубликовать розыгрыш в канал\n"
            "/giveaway_list - список всех розыгрышей\n"
            "/giveaway_members ID - участники конкретного розыгрыша\n"
            "/giveaway_pick ID - выбрать победителя"
        )

    await message.answer(text)


@dp.message(Command("chatid"), F.chat.type == "private")
async def chatid_handler(message: Message):
    await message.answer(f"ID этого чата: <code>{message.chat.id}</code>\nТип чата: <code>{message.chat.type}</code>")


@dp.message(Command("myid"), F.chat.type == "private")
async def myid_handler(message: Message):
    await message.answer(f"Твой user id: <code>{message.from_user.id}</code>")


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

    data = load_giveaways()
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
    }
    save_giveaways(data)

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
    data = load_giveaways()
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
        reply_markup=build_giveaway_preview_kb(giveaway_id)
    )


@dp.callback_query(F.data.startswith("publish_giveaway:"))
async def publish_giveaway_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    giveaway_id = callback.data.split(":", 1)[1]
    data = load_giveaways()
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
            reply_markup=build_giveaway_join_kb(giveaway_id)
        )

        giveaway["posted_message_id"] = sent.message_id
        giveaway["posted_chat_id"] = CHANNEL_ID
        save_giveaways(data)

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
    data = load_giveaways()
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
            reply_markup=build_giveaway_join_kb(giveaway_id)
        )
        giveaway["posted_message_id"] = sent.message_id
        giveaway["posted_chat_id"] = CHANNEL_ID
        save_giveaways(data)

        await message.answer("Розыгрыш опубликован в канал.")
    except Exception as e:
        logging.error(f"Ошибка /giveaway_post: {e}")
        await message.answer("Не удалось опубликовать розыгрыш в канал.")


@dp.message(Command("giveaway_list"), F.chat.type == "private")
async def giveaway_list_handler(message: Message):
    data = load_giveaways()
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
    data = load_giveaways()
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
        f"Всего: <b>{len(giveaway['participants'])}</b>\n\n" +
        "\n".join(members)
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
    data = load_giveaways()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await message.answer("Розыгрыш не найден.")
        return

    if not giveaway["participants"]:
        await message.answer("В розыгрыше нет участников.")
        return

    winner = random.choice(giveaway["participants"])
    winner_id = winner["user_id"]
    winner_username = winner.get("username")
    winner_full_name = winner.get("full_name", "Победитель")

    giveaway["winner"] = winner
    giveaway["is_active"] = False
    save_giveaways(data)

    winner_display = f"@{winner_username}" if winner_username else winner_full_name

    await message.answer(f"🏆 Победитель розыгрыша <b>{giveaway['title']}</b>:\n{winner_display}")

    try:
        await bot.send_message(
            winner_id,
            f"🎉 Ты победил в розыгрыше <b>{giveaway['title']}</b>!"
        )
    except Exception as e:
        logging.warning(f"Не удалось уведомить победителя: {e}")


@dp.message(F.text == "Розыгрыши", F.chat.type == "private")
async def giveaway_menu_handler(message: Message):
    data = load_giveaways()
    active = {gid: g for gid, g in data["giveaways"].items() if g["is_active"]}

    if not active:
        await message.answer("Сейчас активных розыгрышей нет.")
        return

    lines = ["Активные розыгрыши:\n"]
    for gid, g in active.items():
        lines.append(
            f"• <b>{g['title']}</b>\n"
            f"ID: <code>{gid}</code>\n"
            f"Участников: {len(g['participants'])}"
        )

    await message.answer("\n\n".join(lines))


@dp.callback_query(F.data.startswith("refresh_giveaway:"))
async def refresh_giveaway_handler(callback: CallbackQuery):
    giveaway_id = callback.data.split(":", 1)[1]
    data = load_giveaways()
    giveaway = data["giveaways"].get(giveaway_id)

    if not giveaway:
        await callback.answer("Розыгрыш не найден.", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=build_giveaway_join_kb(giveaway_id))
        await callback.answer("Обновлено.")
    except Exception:
        await callback.answer("Нечего обновлять.")


@dp.callback_query(F.data.startswith("join_giveaway:"))
async def join_giveaway_handler(callback: CallbackQuery):
    giveaway_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    if not await check_subscription(user_id):
        await callback.answer("Сначала подпишись на канал.", show_alert=True)
        return

    data = load_giveaways()
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

    giveaway["participants"].append({
        "user_id": user_id,
        "username": callback.from_user.username,
        "full_name": callback.from_user.full_name
    })
    save_giveaways(data)

    try:
        await callback.message.edit_reply_markup(reply_markup=build_giveaway_join_kb(giveaway_id))
    except Exception as e:
        logging.warning(f"Не удалось обновить кнопку участников: {e}")

    await callback.answer("Ты участвуешь!", show_alert=True)


@dp.message(F.text, F.chat.type == "private")
async def redux_select_handler(message: Message):
    redux_key, redux_data = get_redux_by_button(message.text)
    if not redux_data:
        return

    user_selected_redux[message.from_user.id] = redux_key

    await message.answer(
        f"Ты выбрал \"{redux_data['title']}\"\n\n"
        "Чтобы получить редукс:\n\n"
        "1) Подпишись на YouTube-канал:\n"
        "https://www.youtube.com/results?search_query=kaylor5rp\n\n"
        "2) Поставь лайк под видео с обзором редукса:\n"
        f"{redux_data['review_video_link']}\n\n"
        "3) Отправь скриншоты выполнения предыдущих пунктов."
    )


async def process_media_group(media_group_id: str):
    await asyncio.sleep(1.2)

    items = media_group_buffer.get(media_group_id, [])
    if not items:
        return

    first_message = items[0]

    if first_message.chat.type != "private":
        media_group_buffer.pop(media_group_id, None)
        media_group_tasks.pop(media_group_id, None)
        return

    user = first_message.from_user

    if not await check_subscription(user.id):
        await first_message.answer(f"Сначала подпишись на канал {CHANNEL_USERNAME}, потом отправляй скрин.")
        media_group_buffer.pop(media_group_id, None)
        media_group_tasks.pop(media_group_id, None)
        return

    redux_key = user_selected_redux.get(user.id, "afterlight")
    redux_data = REDUXES[redux_key]
    username = user.username or "без username"
    kb = build_admin_kb(user_id=user.id, redux_key=redux_key)

    media = []
    for idx, msg in enumerate(items):
        photo = msg.photo[-1].file_id
        if idx == 0:
            media.append(InputMediaPhoto(
                media=photo,
                caption=(
                    f"<b>Новая заявка: {redux_data['title']}</b>\n"
                    f"Redux key: <code>{redux_key}</code>\n"
                    f"User ID: <code>{user.id}</code>\n"
                    f"Username: @{username}\n"
                ),
                parse_mode=ParseMode.HTML
            ))
        else:
            media.append(InputMediaPhoto(media=photo))

    try:
        sent_messages = await bot.send_media_group(chat_id=ADMIN_CHAT_ID, media=media)
        last_message_id = sent_messages[-1].message_id

        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"Действие по заявке:\n"
                f"<b>{redux_data['title']}</b>\n"
                f"User ID: <code>{user.id}</code>"
            ),
            reply_markup=kb,
            reply_to_message_id=last_message_id
        )

        await first_message.answer(f"Заявка отправлена на проверку.")
    except Exception as e:
        logging.error(f"Ошибка отправки media group в админ-чат: {e}")
        await first_message.answer(
            "Не удалось отправить заявку в чат проверки.\n"
            "Проверь правильность ADMIN_CHAT_ID и что бот добавлен в чат."
        )
    finally:
        media_group_buffer.pop(media_group_id, None)
        media_group_tasks.pop(media_group_id, None)


@dp.message(F.photo, F.chat.type == "private")
async def photo_handler(message: Message):
    if message.media_group_id:
        media_group_buffer[message.media_group_id].append(message)

        if message.media_group_id not in media_group_tasks:
            media_group_tasks[message.media_group_id] = asyncio.create_task(
                process_media_group(message.media_group_id)
            )
        return

    if not await check_subscription(message.from_user.id):
        await message.answer(f"Сначала подпишись на канал {CHANNEL_USERNAME}, потом отправляй скрин.")
        return

    redux_key = user_selected_redux.get(message.from_user.id, "afterlight")
    redux_data = REDUXES[redux_key]
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    kb = build_admin_kb(user_id=user_id, redux_key=redux_key)

    try:
        await bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=message.photo[-1].file_id,
            caption=(
                f"<b>Новая заявка: {redux_data['title']}</b>\n"
                f"Redux key: <code>{redux_key}</code>\n"
                f"User ID: <code>{user_id}</code>\n"
                f"Username: @{username}\n"
            ),
            reply_markup=kb
        )
        await message.answer("Заявка отправлена на проверку.")
    except Exception as e:
        logging.error(f"Ошибка отправки в админ-чат: {e}")
        await message.answer(
            "Не удалось отправить заявку в чат проверки.\n"
            "Проверь правильность ADMIN_CHAT_ID и что бот добавлен в чат."
        )


@dp.callback_query(F.data.startswith("approve:"))
async def approve_handler(callback: CallbackQuery):
    try:
        _, redux_key, user_id_str = callback.data.split(":")
        user_id = int(user_id_str)
        redux_data = REDUXES[redux_key]
    except Exception:
        await callback.answer("Некорректные данные кнопки", show_alert=True)
        return

    try:
        caption = (
            f"{redux_data['title']}\n\n"
            "☝️Просьба, никому не сливать и не кидать попрошайкам, буду очень тебе благодарен, заранее спасибо тебе🥰\n"
            "❗️ИЗ АРХИВА НУЖНО ПЕРЕКИНУТЬ ВСЮ ПАПКУ UPDATE В КОРНЕВУЮ ПАПКУ ИГРЫ❗️\n\n"
            f"Ссылка на скачивание:\n{redux_data['link']}"
        )

        if Path(COMMON_GIF_PATH).exists():
            await bot.send_animation(chat_id=user_id, animation=FSInputFile(COMMON_GIF_PATH), caption=caption)
        else:
            await bot.send_message(chat_id=user_id, text=caption)

        await finish_admin_request_message(
            callback,
            "\n\n✅ Одобрено, ссылка и инструкция отправлены."
        )
        await callback.answer("Готово")
    except Exception as e:
        await callback.answer("Не удалось отправить ссылку", show_alert=True)
        logging.error(f"Ошибка approve: {e}")
@dp.callback_query(F.data.startswith("reject:"))
async def reject_handler(callback: CallbackQuery):
    try:
        _, redux_key, user_id_str = callback.data.split(":")
        user_id = int(user_id_str)
        redux_data = REDUXES.get(redux_key, {"title": "редукс"})
    except Exception:
        await callback.answer("Некорректные данные кнопки", show_alert=True)
        return

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"Заявка на {redux_data['title']} отклонена. Проверь, что подписка и доказательства видны нормально, и отправь заново."
        )

        await finish_admin_request_message(
            callback,
            "\n\n❌ Отклонено."
        )
        await callback.answer("Отклонено")
    except Exception as e:
        await callback.answer("Не удалось отклонить заявку", show_alert=True)
        logging.error(f"Ошибка reject: {e}")

async def finish_admin_request_message(callback: CallbackQuery, status_text: str):
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "Заявка") + status_text,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                (callback.message.text or "Заявка") + status_text,
                reply_markup=None
            )
    except Exception as e:
        logging.error(f"Ошибка обновления сообщения заявки: {e}")


async def main():
    ensure_giveaways_file()
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())


