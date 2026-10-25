import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from dating.bot import make_router
from dating.store import Store
from dating.session import EnvironmentSession
from dating.storage import SQLiteStorage
from dating.maintenance import backup_loop
from dating.runtime import exclusive_instance
from dating.webserver import create_app, API
from dating.notifications import notification_loop
from dating.config import web_settings


async def run(token: str, path: str, admin_id: int | None, webapp_url=None, web_enabled=False):
    store = await Store(path).open()
    directory = os.environ.get('BACKUP_DIR', str(Path(path).parent / 'backups'))
    maintenance = None
    try:
        async with Bot(token, session=EnvironmentSession(), default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
            dispatcher = Dispatcher(storage=SQLiteStorage(store), events_isolation=SimpleEventIsolation())
            dispatcher.include_router(make_router(store, admin_id, webapp_url))
            commands=[
                BotCommand(command='start', description='Главное меню'),
                BotCommand(command='help', description='Данные и безопасность'),
                BotCommand(command='cancel', description='Отмена / выйти из диалога'),
                BotCommand(command='delete', description='Удалить мои данные'),
                BotCommand(command='id', description='Мой Telegram ID'),
            ]
            runner, notifications = None, None
            try:
                if web_enabled or webapp_url:
                    bootstrap=os.environ.get('MIGRATION_MODE')=='1' and await store.needs_bootstrap()
                    application=create_app(store, bot, token, admin_id, bootstrap, webapp_url)
                    runner = web.AppRunner(application, access_log=None)
                    await runner.setup()
                    settings = web_settings(os.environ)
                    await web.TCPSite(runner, settings.host, settings.port).start()
                    logging.getLogger(__name__).info('Mini App HTTP server started')
                    if bootstrap:
                        logging.getLogger(__name__).info('Awaiting authenticated database bootstrap before polling')
                        await application[API].ready.wait()
                maintenance = asyncio.create_task(backup_loop(path, directory)) if directory else None
                await bot.set_my_commands(commands)
                await bot.delete_webhook(drop_pending_updates=False)
                if webapp_url:
                    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='Открыть Мэтч', web_app=WebAppInfo(url=webapp_url)))
                    notifications = asyncio.create_task(notification_loop(store, bot, webapp_url))
                await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types(), close_bot_session=False)
            finally:
                if notifications:
                    notifications.cancel()
                    with suppress(asyncio.CancelledError):
                        await notifications
                if runner:
                    await runner.cleanup()
    finally:
        if maintenance:
            maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance
        await store.close()


def main():
    token = os.environ.get('BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Задайте BOT_TOKEN через окружение. Получите токен у @BotFather; не добавляйте его в Git.')
    admin = os.environ.get('ADMIN_ID', '').strip()
    if admin and (not admin.isascii() or not admin.isdigit()):
        raise SystemExit('ADMIN_ID должен быть числовым Telegram ID.')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    # HTTP diagnostics can contain bot API URLs; keep them disabled.
    logging.getLogger('aiohttp').setLevel(logging.CRITICAL)
    try:
        path = os.environ.get('DATABASE_PATH', 'data/dating.sqlite3')
        settings = web_settings(os.environ)
        with exclusive_instance(path):
            asyncio.run(run(token, path, int(admin) if admin else None, settings.url, settings.enabled))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        # Never print exceptions containing request URLs or token-bearing paths.
        raise SystemExit(f'Бот остановлен ({type(exc).__name__}). Проверьте токен, сеть и доступ к базе.') from None


if __name__ == '__main__':
    main()
