from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.database import Channel, ScheduledPost


def channels_keyboard(channels: List[Channel], selected: List[int] | None = None) -> InlineKeyboardMarkup:
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for ch in channels:
        mark = "✅ " if ch.id in selected else ""
        title = ch.title[:40] + ("…" if len(ch.title) > 40 else "")
        builder.button(text=f"{mark}{title}", callback_data=f"toggle_ch:{ch.id}")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_channels"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_post")
    )
    return builder.as_markup()


def scheduled_posts_keyboard(posts: List[ScheduledPost]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for post in posts:
        time_str = post.scheduled_at.strftime("%d.%m.%Y %H:%M")
        builder.button(
            text=f"#{post.id} — {time_str} [{post.status}]",
            callback_data=f"post_info:{post.id}"
        )
    builder.adjust(1)
    return builder.as_markup()


def post_actions_keyboard(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🕒 Vaqtini o'zgartirish", callback_data=f"edit_time:{post_id}")
    builder.button(text="❌ Bekor qilish", callback_data=f"cancel_post_id:{post_id}")
    builder.button(text="◀️ Orqaga", callback_data="back_to_scheduled")
    builder.adjust(1)
    return builder.as_markup()


def confirm_post_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ha, rejalashtirish", callback_data="confirm_schedule")
    builder.button(text="❌ Bekor qilish", callback_data="cancel_post")
    builder.adjust(1)
    return builder.as_markup()


def timezone_keyboard() -> InlineKeyboardMarkup:
    popular = [
        ("Asia/Tashkent", "🇺🇿 Toshkent"),
        ("Asia/Almaty", "🇰🇿 Almaty"),
        ("Europe/Moscow", "🇷🇺 Moskva"),
        ("Asia/Baku", "🇦🇿 Boku"),
        ("Europe/Istanbul", "🇹🇷 Istanbul"),
        ("UTC", "🌍 UTC"),
    ]
    builder = InlineKeyboardBuilder()
    for tz, name in popular:
        builder.button(text=name, callback_data=f"set_tz:{tz}")
    builder.adjust(2)
    return builder.as_markup()
