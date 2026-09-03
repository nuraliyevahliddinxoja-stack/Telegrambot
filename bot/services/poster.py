import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select

from bot.models.database import async_session, ScheduledPost, Channel, User

logger = logging.getLogger(__name__)


async def send_post_to_channels(bot: Bot, post_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledPost).where(ScheduledPost.id == post_id)
        )
        post = result.scalar_one_or_none()
        if not post or post.status != "pending":
            return

        owner_result = await session.execute(
            select(User).where(User.id == post.owner_id)
        )
        owner = owner_result.scalar_one_or_none()
        if not owner:
            post.status = "failed"
            post.error_message = "Owner topilmadi"
            await session.commit()
            return

        target_ids = post.get_target_ids()
        content = post.get_content()
        success_count = 0
        errors = []

        for ch_id in target_ids:
            ch_result = await session.execute(
                select(Channel).where(
                    Channel.id == ch_id,
                    Channel.owner_id == post.owner_id,
                    Channel.is_active == True
                )
            )
            channel = ch_result.scalar_one_or_none()
            if not channel:
                errors.append(f"Kanal {ch_id} topilmadi yoki faol emas")
                continue

            try:
                member = await bot.get_chat_member(channel.chat_id, bot.id)
                if member.status not in ("administrator", "creator"):
                    errors.append(f"{channel.title}: bot admin emas")
                    continue
            except Exception as e:
                errors.append(f"{channel.title}: tekshiruv xatosi — {e}")
                continue

            try:
                await _send_content(
                    bot, channel.chat_id, post.content_type,
                    content, post.caption, post.parse_mode
                )
                success_count += 1
                await asyncio.sleep(0.4)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await _send_content(
                        bot, channel.chat_id, post.content_type,
                        content, post.caption, post.parse_mode
                    )
                    success_count += 1
                except Exception as e2:
                    errors.append(f"{channel.title}: {e2}")
            except (TelegramForbiddenError, TelegramBadRequest) as e:
                errors.append(f"{channel.title}: {e}")
            except Exception as e:
                errors.append(f"{channel.title}: {e}")
                logger.exception("Post yuborishda xato")

        if success_count > 0 and not errors:
            post.status = "sent"
            post.sent_at = datetime.utcnow()
            msg = f"✅ Post #{post.id} muvaffaqiyatli yuborildi ({success_count} ta kanal)."
        elif success_count > 0:
            post.status = "sent"
            post.sent_at = datetime.utcnow()
            post.error_message = "; ".join(errors)
            msg = f"⚠️ Post #{post.id} qisman yuborildi ({success_count} ta). Xatolar: {post.error_message}"
        else:
            post.status = "failed"
            post.error_message = "; ".join(errors) if errors else "Noma'lum xato"
            msg = f"❌ Post #{post.id} yuborilmadi.\n{post.error_message}"

        await session.commit()

        try:
            await bot.send_message(owner.telegram_id, msg)
        except Exception:
            pass


async def _send_content(bot: Bot, chat_id: int, content_type: str, content: dict, caption: str | None, parse_mode: str | None):
    if content_type == "text":
        await bot.send_message(chat_id, content["text"], parse_mode=parse_mode)
    elif content_type == "photo":
        await bot.send_photo(chat_id, content["file_id"], caption=caption, parse_mode=parse_mode)
    elif content_type == "video":
        await bot.send_video(chat_id, content["file_id"], caption=caption, parse_mode=parse_mode)
    elif content_type == "document":
        await bot.send_document(chat_id, content["file_id"], caption=caption, parse_mode=parse_mode)
    elif content_type == "voice":
        await bot.send_voice(chat_id, content["file_id"], caption=caption, parse_mode=parse_mode)
    elif content_type == "animation":
        await bot.send_animation(chat_id, content["file_id"], caption=caption, parse_mode=parse_mode)
    elif content_type == "media_group":
        media = []
        items = content.get("items", [])
        for i, item in enumerate(items):
            media_type = item["type"]
            file_id = item["file_id"]
            cap = caption if i == 0 else None
            pm = parse_mode if i == 0 else None
            if media_type == "photo":
                media.append(InputMediaPhoto(media=file_id, caption=cap, parse_mode=pm))
            elif media_type == "video":
                media.append(InputMediaVideo(media=file_id, caption=cap, parse_mode=pm))
            elif media_type == "document":
                media.append(InputMediaDocument(media=file_id, caption=cap, parse_mode=pm))
        if media:
            await bot.send_media_group(chat_id, media)
    else:
        raise ValueError(f"Noma'lum content_type: {content_type}")
