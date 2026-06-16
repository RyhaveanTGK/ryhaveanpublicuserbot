from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config import settings

log = logging.getLogger("ryhavean.bot")

bot = Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None
dp = Dispatcher()
_bot_task: asyncio.Task | None = None


def build_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Open Web App",
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            ]
        ]
    )


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(settings.start_message, reply_markup=build_start_keyboard())


@dp.message(F.web_app_data)
async def web_app_data_handler(message: Message) -> None:
    await message.answer(
    "🌌 Ryhavean\n\n"
    "Salam, Ryhavean'a xoş gəldin! 👋\n\n"
    "⚡ Güclü Telegram Userbot\n"
    "🛡 Stabil və təhlükəsiz\n"
    "🔌 Plugin dəstəyi\n"
    "🚀 Sürətli idarəetmə\n\n"
    "Aşağıdakı düyməyə toxunaraq idarəetmə panelini aça bilərsən.\n\n"
    "✨ Ryhavean — Sadəcə Userbot deyil, tam idarəetmə təcrübəsi."
)


async def start_bot_polling() -> None:
    global _bot_task
    if not bot:
        log.warning("TELEGRAM_BOT_TOKEN təyin edilmədiyi üçün bot polling başlamadı")
        return

    async def _runner() -> None:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    if _bot_task and not _bot_task.done():
        return
    _bot_task = asyncio.create_task(_runner(), name="ryhavean-bot")


async def stop_bot_polling() -> None:
    global _bot_task
    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            pass
    _bot_task = None
    if bot:
        await bot.session.close()
