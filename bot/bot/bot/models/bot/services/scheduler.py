import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from aiogram import Bot

from bot.config import DATABASE_URL
from bot.services.poster import send_post_to_channels

logger = logging.getLogger(__name__)

jobstore_url = DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")

jobstores = {
    "default": SQLAlchemyJobStore(url=jobstore_url)
}

scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")


def start_
