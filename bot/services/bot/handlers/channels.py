from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from bot.models.database import async_session, User, Channel
from bot.states.forms import AddChannelStates

router = Router()


async def get_or_create_user(session, telegram_id: int) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


@router.message(Command("addchannel"))
async def cmd_addchannel(message: Message, state: FSMContext):
    await state.set_state(AddChannelStates.waiting_for_forward)
    await message.answer(
        "📢 Kanal yoki guruhni qo'shish:\n\n"
        "1. Botni kanalga <b>admin</b> qiling.\n"
        "2. Shu chatdan xabarni menga <b>forward</b> qiling.\n"
        "Yoki @username yuboring.\n\n"
        "Bekor qilish: /cancel"
    )


@router.message(AddChannelStates.waiting_for_forward)
async def process_channel_forward(message: Message, state: FSMContext, bot: Bot):
    chat_id = None
    title = None
    username = None

    if message.forward_from_chat:
        chat = message.forward_from_chat
        chat_id = chat.id
        title = chat.title or "Nomsiz"
        username = chat.username
    elif message.text and message.text.startswith("@"):
        try:
            chat = await bot.get_chat(message.text)
            chat_id = chat.id
            title = chat.title or message.text
            username = chat.username
        except Exception:
            await message.answer("❌ Kanal topilmadi.")
            return
    else:
        await message.answer("❌ Forward qiling yoki @username yuboring. /cancel")
        return

    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await message.answer("❌ Bot bu yerda admin emas.")
            return
    except Exception as e:
        await message.answer(f"❌ Chatga kirib bo'lmadi: {e}")
        return

    try:
        user_member = await bot.get_chat_member(chat_id, message.from_user.id)
        if user_member.status not in ("administrator", "creator"):
            await message.answer("❌ Siz bu yerda admin emassiz.")
            return
    except Exception:
        await message.answer("❌ Adminlikni tekshirib bo'lmadi.")
        return

    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        existing = await session.execute(
            select(Channel).where(Channel.owner_id == user.id, Channel.chat_id == chat_id)
        )
        if existing.scalar_one_or_none():
            await message.answer("ℹ️ Bu kanal allaqachon bor.")
            await state.clear()
            return

        channel = Channel(
            owner_id=user.id,
            chat_id=chat_id,
            title=title,
            username=username,
            verified_at=datetime.utcnow()
        )
        session.add(channel)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Kanal qo'shildi!\n\n<b>{title}</b>\nID: <code>{chat_id}</code>",
        parse_mode="HTML"
    )


@router.message(Command("mychannels"))
async def cmd_mychannels(message: Message):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        result = await session.execute(
            select(Channel).where(Channel.owner_id == user.id, Channel.is_active == True)
        )
        channels = result.scalars().all()

    if not channels:
        await message.answer("📭 Kanal yo'q. /addchannel")
        return

    text = "📋 <b>Sizning kanallaringiz:</b>\n\n"
    for i, ch in enumerate(channels, 1):
        uname = f" (@{ch.username})" if ch.username else ""
        text += f"{i}. <b>{ch.title}</b>{uname}\n   ID: <code>{ch.chat_id}</code>\n\n"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("removechannel"))
async def cmd_removechannel(message: Message):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        result = await session.execute(
            select(Channel).where(Channel.owner_id == user.id, Channel.is_active == True)
        )
        channels = result.scalars().all()

    if not channels:
        await message.answer("📭 O'chirish uchun kanal yo'q.")
        return

    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.button(text=f"❌ {ch.title[:30]}", callback_data=f"rm_ch:{ch.id}")
    builder.adjust(1)
    await message.answer("Qaysi kanalni o'chirasiz?",
