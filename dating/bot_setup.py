"""Register visible entry points, including the owner's explicit chat menu."""
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonWebApp, WebAppInfo

log = logging.getLogger(__name__)


async def configure_bot(bot, webapp_url=None, admin_id=None):
    commands = [BotCommand(command='start', description='Главное меню')]
    if webapp_url:
        commands.append(BotCommand(command='app', description='Открыть приложение Мэтч'))
    commands += [
        BotCommand(command='help', description='Данные и безопасность'),
        BotCommand(command='cancel', description='Отмена / выйти из диалога'),
        BotCommand(command='delete', description='Удалить мои данные'),
        BotCommand(command='id', description='Мой Telegram ID'),
    ]
    await bot.set_my_commands(commands)
    if webapp_url:
        menu = MenuButtonWebApp(text='Открыть Мэтч', web_app=WebAppInfo(url=webapp_url))
        await bot.set_chat_menu_button(menu_button=menu)
    if admin_id:
        try:
            await bot.set_my_commands(commands + [BotCommand(command='admin', description='Админ-панель')],
                                      scope=BotCommandScopeChat(chat_id=admin_id))
            if webapp_url:
                await bot.set_chat_menu_button(chat_id=admin_id, menu_button=menu)
        except (TelegramBadRequest, TelegramForbiddenError):
            # A fresh installation may not yet have a conversation with its owner.
            log.warning('Owner chat menu unavailable; global bot commands remain configured')
