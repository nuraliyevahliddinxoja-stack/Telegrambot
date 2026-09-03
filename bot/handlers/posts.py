import json
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.models.database import async_session, Channel, ScheduledPost
from bot.states.forms import NewPostStates, EditPostStates
from bot.keyboards.inline import channels_keyboard, confirm_post_keyboard, timezone_keyboard
from bot.services.scheduler import schedule_post, reschedule_job
from bot.handlers.channels import get_or_create_user

router = Router()


@router.message(Command("newpost"))
async def cmd_newpost(message: Message, state: FSMContext):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        result = await session.execute(
            select(Channel).where(Channel.owner_id == user.id, Channel.is_active == True)
        )
        channels = result.scalars().all()

    if not channels:
        await message.answer("❌ Avval kanal qo'shing.\n/addchannel")
        return

    await state.set_state(NewPostStates.waiting_for_content)
    await state.update_data(selected_channels=[])
    await message.answer(
        "📝 Yangi post.\n\n"
        "Menga yuboring: matn, rasm, video, hujjat, ovoz yoki albom.\n\n"
        "Bekor qilish: /cancel"
    )


@router.message(NewPostStates.waiting_for_content, F.media_group_id)
async def process_media_group(message: Message, state: FSMContext):
    data = await state.get_data()
    media_group_id = message.media_group_id

    if "media_items" not in data or data.get("current_media_group") != media_group_id:
        await state.update_data(
            media_items=[],
            current_media_group=media_group_id,
            caption=message.caption,
            parse_mode="HTML" if message.caption_entities else None
        )
        data = await state.get_data()

    item = None
    if message.photo:
        item = {"type": "photo", "file_id": message.photo[-1].file_id}
    elif message.video:
        item = {"type": "video", "file_id": message.video.file_id}
    elif message.document:
        item = {"type": "document", "file_id": message.document.file_id}

    if item:
        items = data.get("media_items", [])
        items.append(item)
        await state.update_data(media_items=items)

    import asyncio
    await asyncio.sleep(1.0)

    data = await state.get_data()
    if data.get("media_processed"):
        return
    await state.update_data(media_processed=True)

    items = data.get("media_items", [])
    if not items:
        await message.answer("Media topilmadi, qayta yuboring.")
        return

    await state.update_data(
        content_type="media_group",
        content_data={"items": items},
        caption=data.get("caption"),
        parse_mode=data.get("parse_mode")
    )
    await ask_datetime(message, state)


@router.message(NewPostStates.waiting_for_content)
async def process_content(message: Message, state: FSMContext):
    content_type = None
    content_data = {}
    caption = message.caption
    parse_mode = "HTML" if (message.entities or message.caption_entities) else None

    if message.text and not message.media_group_id:
        content_type = "text"
        content_data = {"text": message.html_text or message.text}
        caption = None
        parse_mode = "HTML"
    elif message.photo:
        content_type = "photo"
        content_data = {"file_id": message.photo[-1].file_id}
    elif message.video:
        content_type = "video"
        content_data = {"file_id": message.video.file_id}
    elif message.document:
        content_type = "document"
        content_data = {"file_id": message.document.file_id}
    elif message.voice:
        content_type = "voice"
        content_data = {"file_id": message.voice.file_id}
    elif message.animation:
        content_type = "animation"
        content_data = {"file_id": message.animation.file_id}
    else:
        await message.answer("❌ Qo'llab-quvvatlanmaydigan format.")
        return

    await state.update_data(
        content_type=content_type,
        content_data=content_data,
        caption=caption,
        parse_mode=parse_mode
    )
    await ask_datetime(message, state)


async def ask_datetime(message: Message, state: FSMContext):
    await state.set_state(NewPostStates.waiting_for_datetime)
    await message.answer(
        "📅 Qachon joylashtirilsin?\n\n"
        "Format: <code>YYYY-MM-DD HH:MM</code>\n"
        "Masalan: <code>2026-09-15 14:30</code>\n\n"
        "Vaqt zonasi: /settimezone",
        parse_mode="HTML"
    )


@router.message(NewPostStates.waiting_for_datetime)
async def process_datetime(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        local_dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Format: <code>2026-09-15 14:30</code>", parse_mode="HTML")
        return

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        tz_name = user.timezone or "Asia/Tashkent"

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Tashkent")

    local_aware = local_dt.replace(tzinfo=tz)
    utc_dt = local_aware.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    if utc_dt <= datetime.utcnow():
        await message.answer("❌ Vaqt o'tmishda bo'lishi mumkin emas.")
        return

    await state.update_data(scheduled_at=utc_dt.isoformat(), local_time=text)

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        result = await session.execute(
            select(Channel).where(Channel.owner_id == user.id, Channel.is_active == True)
        )
        channels = result.scalars().all()

    await state.set_state(NewPostStates.waiting_for_channels)
    await state.update_data(selected_channels=[])
    await message.answer(
        "📢 Qaysi kanal(lar)ga?\nKeraklilarini belgilang, keyin Tasdiqlash.",
        reply_markup=channels_keyboard(channels, [])
    )


@router.callback_query(NewPostStates.waiting_for_channels, F.data.startswith("toggle_ch:"))
async def toggle_channel(callback: CallbackQuery, state: FSMContext):
    ch_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("selected_channels", [])
    if ch_id in selected:
        selected.remove(ch_id)
    else:
        selected.append(ch_id)
    await state.update_data(selected_channels=selected)

    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        result = await session.execute(
            select(Channel).where(Channel.owner_id == user.id, Channel.is_active == True)
        )
        channels = result.scalars().all()

    await callback.message.edit_reply_markup(reply_markup=channels_keyboard(channels, selected))
    await callback.answer()


@router.callback_query(NewPostStates.waiting_for_channels, F.data == "confirm_channels")
async def confirm_channels(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_channels", [])
    if not selected:
        await callback.answer("Kamida bitta kanal tanlang!", show_alert=True)
        return

    await state.set_state(NewPostStates.confirming)

    async with async_session() as session:
        result = await session.execute(select(Channel).where(Channel.id.in_(selected)))
        channels = result.scalars().all()

    ch_names = ", ".join(ch.title for ch in channels)
    local_time = data.get("local_time", "?")
    text = (
        f"📋 <b>Tasdiqlash</b>\n\n"
        f"🕒 Vaqt: <b>{local_time}</b>\n"
        f"📢 Kanallar: <b>{ch_names}</b>\n"
        f"📄 Tur: <code>{data.get('content_type')}</code>\n\n"
        f"Rejalashtirasizmi?"
    )
    await callback.message.edit_text(text, reply_markup=confirm_post_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(NewPostStates.confirming, F.data == "confirm_schedule")
async def confirm_schedule(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_channels", [])
    scheduled_at = datetime.fromisoformat(data["scheduled_at"])

    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        post = ScheduledPost(
            owner_id=user.id,
            content_type=data["content_type"],
            content_data=json.dumps(data["content_data"]),
            caption=data.get("caption"),
            parse_mode=data.get("parse_mode"),
            target_channel_ids=json.dumps(selected),
            scheduled_at=scheduled_at,
            status="pending"
        )
        session.add(post)
        await session.commit()
        await session.refresh(post)
        job_id = schedule_post(post.id, scheduled_at)
        post.job_id = job_id
        await session.commit()

    await state.clear()
    await callback.message.edit_text(
        f"✅ Post rejalashtirildi!\n\nID: <b>#{post.id}</b>\nVaqt: <b>{data.get('local_time')}</b>\n\n/scheduled",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_post")
async def cancel_post_creation(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Post yaratish bekor qilindi.")
    await callback.answer()


@router.message(Command("settimezone"))
async def cmd_settimezone(message: Message):
    await message.answer("🌍 Vaqt zonasini tanlang:", reply_markup=timezone_keyboard())


@router.callback_query(F.data.startswith("set_tz:"))
async def process_timezone_callback(callback: CallbackQuery):
    tz = callback.data.split(":", 1)[1]
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user.timezone = tz
        await session.commit()
    await callback.message.edit_text(f"✅ Vaqt zonasi: <b>{tz}</b>", parse_mode="HTML")
    await callback.answer()
