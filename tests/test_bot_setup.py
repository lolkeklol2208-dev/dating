from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SetMyCommands

from dating.bot_setup import configure_bot


async def test_public_entry_and_owner_commands_and_menu_are_configured_separately():
    bot = SimpleNamespace(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    await configure_bot(bot, 'https://metch.example.test/', 99)
    general, owner = bot.set_my_commands.call_args_list
    assert 'app' in {command.command for command in general.args[0]}
    assert 'admin' not in {command.command for command in general.args[0]}
    assert owner.kwargs['scope'].chat_id == 99
    assert 'admin' in {command.command for command in owner.args[0]}
    menus = bot.set_chat_menu_button.call_args_list
    assert len(menus) == 2 and menus[1].kwargs['chat_id'] == 99
    assert all(call.kwargs['menu_button'].web_app.url == 'https://metch.example.test/' for call in menus)


async def test_unknown_owner_chat_does_not_stop_a_fresh_deployment():
    error = TelegramBadRequest(method=SetMyCommands(commands=[]), message='chat not found')
    bot = SimpleNamespace(set_my_commands=AsyncMock(side_effect=[True, error]), set_chat_menu_button=AsyncMock())
    await configure_bot(bot, 'https://metch.example.test/', 99)
    bot.set_chat_menu_button.assert_awaited_once()


async def test_legacy_bot_keeps_working_without_a_mini_app_url():
    bot = SimpleNamespace(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    await configure_bot(bot)
    assert 'app' not in {command.command for command in bot.set_my_commands.call_args.args[0]}
    bot.set_chat_menu_button.assert_not_awaited()
