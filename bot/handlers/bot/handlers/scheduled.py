from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.models.database import async_session, ScheduledPost, Channel
from bot.states.forms import EditPostStates
from bot.keyboards.inline import scheduled_posts_keyboard, post_actions_keyboard
from bot.services.scheduler import cancel_job, reschedule_job, schedule_post
from bot.handlers.channels import get_or_create_user

router = Router()


@router.message(Command("scheduled"))
async def cmd_scheduled(message: Message):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        result = await session.execute(
            select(ScheduledPost)
            .where(ScheduledPost.owner_id == user.id, ScheduledPost.status == "pending")
            .order_by(ScheduledPost.scheduled_at)
        )
        posts = result.scalars().all()

    if not posts:
        await message.answer("📭 Kutilayotgan postlar yo'q.")
        return

    tz_name = user.timezone or "Asia/Tashkent"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Tashkent")

    text = "📋 <b>Kutilayotgan postlar:</b>\n\n"
    for post in posts:
        utc_dt = post.scheduled_at.replace(tzinfo=ZoneInfo("UTC"))
        local_dt = utc_dt.astimezone(tz)
        time_str = local_dt.strftime("%d.%m.%Y %H:%M")
        text += f"• <b>#{post.id}</b> — {time_str} — <code>{post.content_type}</code>\n"

    await message.answer(text, reply_markup=scheduled_posts_keyboard(posts), parse_mode="HTML")


@router.callback_query(F.data.startswith("post_info:"))
async def post_info(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        result = await session.execute(
            select(ScheduledPost).where(
                ScheduledPost.id == post_id,
                ScheduledPost.owner_id == user.id
            )
        )
        post = result.scalar_one_or_none()
        if not post:
            await callback.answer("Post topilmadi", show_alert=True)
            return

        target_ids = post.get_target_ids()
        ch_result = await session.execute(select(Channel).where(Channel.id.in_(target_ids)))
        channels = ch_result.scalars().all()
        ch_names = ", ".join(ch.title for ch in channels) or "—"

        tz_name = user.timezone or "Asia/Tashkent"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Asia/Tashkent")
        utc_dt = post.scheduled_at.replace(tzinfo=ZoneInfo("UTC"))
        local_dt = utc_dt.astimezone(tz)
        time_str = local_dt.strftime("%d.%m.%Y %H:%M")

    text = (
        f"📄 <b>Post #{post.id}</b>\n\n"
        f"🕒 Vaqt: <b>{time_str}</b>\n"
        f"📢 Kanallar: {ch_names}\n"
        f"📄 Tur: <code>{post.content_type}</code>\n"
        f"📊 Status: <b>{post.status}</b>\n"
    )
    if post.caption:
        text += f"\n💬 Caption: {post.caption[:200]}"

    await callback.message.edit_text(text, reply_markup=post_actions_keyboard(post.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_post_id:"))
async def cancel_scheduled_post(callback: CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        result = await session.execute(
            select(ScheduledPost).where(
                ScheduledPost.id == post_id,
                ScheduledPost.owner_id == user.id,
                ScheduledPost.status == "pending"
            )
        )
        post = result.scalar_one_or_none()
        if not post:
            await callback.answer("Post topilmadi", show_alert=True)
            return
        if post.job_id:
            cancel_job(post.job_id)
        post.status = "cancelled"
        await session.commit()
    await callback.message.edit_text(f"✅ Post #{post_id} bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data.startswith("edit_time:"))
async def start_edit_time(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    await state.set_state(EditPostStates.waiting_for_new_datetime)
    await state.update_data(edit_post_id=post_id)
    await callback.message.edit_text(
        f"🕒 Post #{post_id} uchun yangi vaqt:\nFormat: <code>YYYY-MM-DD HH:MM</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditPostStates.waiting_for_new_datetime)
async def process_new_datetime(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        local_dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Format: 2026-09-15 14:30")
        return

    data = await state.get_data()
    post_id = data.get("edit_post_id")

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

        result = await session.execute(
            select(ScheduledPost).where(
                ScheduledPost.id == post_id,
                ScheduledPost.owner_id == user.id,
                ScheduledPost.status == "pending"
            )
        )
        post = result.scalar_one_or_none()
        if not post:
            await message.answer("Post topilmadi.")
            await state.clear()
            return

        post.scheduled_at = utc_dt
        if post.job_id:
            reschedule_job(post.job_id, utc_dt)
        else:
            post.job_id = schedule_post(post.id, utc_dt)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Post #{post_id} vaqti: <b>{text}</b>", parse_mode="HTML")


@router.callback_query(F.data == "back_to_scheduled")
async def back_to_scheduled(callback: CallbackQuery):
    await callback.message.edit_text("Ro'yxat: /scheduled")
    await callback.answer()
