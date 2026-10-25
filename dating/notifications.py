import asyncio
import logging
import time
from urllib.parse import urlencode

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

log = logging.getLogger(__name__)


def app_keyboard(url, target=None):
    if target:
        url = url.rstrip('/') + '/?' + urlencode({'chat': target})
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Открыть Мэтч 💜', web_app=WebAppInfo(url=url))]])


async def deliver_once(store, bot, url):
    for item in await store.pending_notifications(time.time()):
        if not await store.can_chat(item['recipient'], item['sender']):
            await store.finish_notification(item['id'], True)
            continue
        person = await store.profile(item['sender'])
        text = ('💜 У вас новый мэтч! Симпатия взаимна — познакомьтесь ближе.' if item['kind'] == 'match'
                else '💬 Новое сообщение в Мэтч. Откройте диалог, чтобы ответить.')
        if not person:
            await store.finish_notification(item['id'], True)
            continue
        try:
            await bot.send_message(item['recipient'], text, reply_markup=app_keyboard(url, item['sender']))
        except (TelegramForbiddenError, TelegramBadRequest):
            await store.finish_notification(item['id'], True)
            log.warning('Telegram notification unavailable; chat data retained')
        except (TelegramNetworkError, TelegramRetryAfter) as exc:
            delay = getattr(exc, 'retry_after', min(3600, 5 * 2 ** item['attempts']))
            await store.finish_notification(item['id'], item['attempts'] >= 9, time.time() + delay)
        else:
            await store.finish_notification(item['id'], True)


async def notification_loop(store, bot, url):
    while True:
        try:
            await deliver_once(store, bot, url)
        except Exception as exc:
            log.error('Notification worker failed (%s)', type(exc).__name__)
        await asyncio.sleep(3)
