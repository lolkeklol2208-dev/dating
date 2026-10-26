"""Private match-only messaging and authorized moderation routes."""
import logging
from html import escape

from aiogram import F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dating.admin_store import ModerationConflict

log = logging.getLogger(__name__)
DELIVERY_ERRORS = (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError)


def register_features(router, store, admin_id, keyboard, home, webapp_url=None):
    @router.message(Command('delete'))
    async def delete_command(message: Message):
        await message.answer('Удалить анкету и черновики? Это действие нельзя отменить.',
            reply_markup=keyboard([('Да, удалить', 'delete:yes')], [('Отмена', 'home')]))

    @router.message(Command('admin'))
    async def admin(message: Message):
        if message.from_user.id != admin_id:
            await message.answer('Этот раздел доступен только модератору.')
            return
        stats = await store.stats()
        markup = keyboard([('Новые жалобы', 'admin:reports')])
        if webapp_url:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='Открыть админ-панель',
                    web_app=WebAppInfo(url=webapp_url.rstrip('/')+'/?view=admin'))]])
        await message.answer('<b>Мэтч · Модерация</b>\n' + '\n'.join([
            f'Анкеты: {stats["profiles"]}', f'Совпадения: {stats["matches"]}',
            f'Сообщения: {stats["messages"]}', f'Жалобы: {stats["reports"]}', f'Баны: {stats["bans"]}']),
            reply_markup=markup)

    @router.callback_query(F.data == 'admin:reports')
    async def reports(call: CallbackQuery):
        if call.from_user.id != admin_id:
            await call.answer('Нет доступа', show_alert=True)
            return
        await call.answer()
        rows = await store.reports()
        if not rows:
            await call.message.answer('Необработанных жалоб нет.')
        for row in rows:
            target = await store.profile(row['target'])
            if not target:
                continue
            await call.message.answer_photo(target['photo'], caption=(
                f'<b>Жалоба · {escape(row["reason"])}</b>\n'
                f'От: {row["actor"]} · На: {row["target"]}\n'
                f'{escape(target["name"])}, {target["age"]}\n'
                f'{escape(target["city"])}\n{escape(target["bio"])}'),
                reply_markup=keyboard([('Забанить', f'mod:ban:{row["actor"]}:{row["target"]}')],
                                      [('Отклонить жалобу', f'mod:close:{row["actor"]}:{row["target"]}')]))

    @router.callback_query(F.data.regexp(r'^mod:(ban|close):\d+:\d+$'))
    async def moderate(call: CallbackQuery):
        if call.from_user.id != admin_id:
            await call.answer('Нет доступа', show_alert=True)
            return
        _, action, actor, target = call.data.split(':')
        await call.answer()
        if int(target) == admin_id and action == 'ban':
            await call.message.answer('Нельзя заблокировать собственный аккаунт модератора.')
            return
        if action == 'ban':
            await call.message.answer('Подтвердить блокировку пользователя во всём боте?', reply_markup=keyboard(
                [('Подтвердить бан', f'modconfirm:{actor}:{target}')], [('Отмена', 'admin:reports')]))
        else:
            try:
                await store.moderate(admin_id, int(target), 'dismiss', 'Отклонено модератором в боте', int(actor))
            except (ModerationConflict, ValueError) as exc:
                await call.message.answer(escape(str(exc)))
                return
            await call.message.answer('Жалоба закрыта. Личная блокировка заявителя сохранена.')

    @router.callback_query(F.data.regexp(r'^modconfirm:\d+:\d+$'))
    async def confirm_ban(call: CallbackQuery):
        if call.from_user.id != admin_id:
            await call.answer('Нет доступа', show_alert=True)
            return
        _, actor, target = call.data.split(':')
        if int(target) == admin_id:
            await call.answer('Нельзя забанить себя', show_alert=True)
            return
        try:
            await store.moderate(admin_id, int(target), 'ban', 'Жалоба подтверждена модератором в боте', int(actor))
        except (ModerationConflict, ValueError) as exc:
            await call.answer(str(exc), show_alert=True)
            return
        await call.answer('Пользователь заблокирован')
        await call.message.answer(f'Бан применён к ID {target}. Для снятия: /unban {target}')

    @router.message(Command('unban'))
    async def unban(message: Message):
        if message.from_user.id != admin_id:
            await message.answer('Нет доступа.')
            return
        parts = (message.text or '').split()
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
            await message.answer('Использование: /unban Telegram_ID')
            return
        try:
            await store.moderate(admin_id, int(parts[1]), 'unban', 'Блокировка снята модератором в боте')
        except (ModerationConflict, ValueError) as exc:
            await message.answer(escape(str(exc)))
            return
        await message.answer('Бан снят. Личные блокировки участников сохраняются.')

    @router.message(Command('id'))
    async def identity(message: Message):
        await message.answer(f'Ваш Telegram ID: <code>{message.from_user.id}</code>')

    @router.callback_query(F.data.regexp(r'^chat:\d+$'))
    async def open_chat(call: CallbackQuery, state):
        target = int(call.data.split(':')[1])
        if not await store.select_chat(call.from_user.id, target):
            await call.answer('Диалог недоступен', show_alert=True)
            return
        await call.answer()
        await state.clear()
        p = await store.profile(target)
        await call.message.answer(f'<b>Диалог · {escape(p["name"])}</b>\n\n'
            'Напишите текст — я передам его собеседнику без пересылки вашего профиля. '
            'Сообщения сохраняются в истории. Поддерживается текст до 2000 символов.\n\n'
            'Отправка не означает, что сообщение прочитано. Кнопка «Выйти» остановит отправку в этот диалог.',
            reply_markup=chat_buttons(target, keyboard))

    @router.callback_query(F.data == 'chat:leave')
    async def leave(call: CallbackQuery):
        await store.leave_chat(call.from_user.id)
        await call.answer('Вы вышли из диалога')
        await call.message.answer('Вы в меню. Текст больше не будет отправляться собеседнику.', reply_markup=home)

    @router.callback_query(F.data.regexp(r'^history:\d+:\d+$'))
    async def history(call: CallbackQuery):
        _, target, before = call.data.split(':')
        target, before = int(target), min(int(before), 9223372036854775807)
        if not await store.can_chat(call.from_user.id, target):
            await call.answer('Диалог недоступен', show_alert=True)
            return
        await call.answer()
        rows = await store.history(call.from_user.id, target, before)
        if not rows:
            await call.message.answer('Более ранних сообщений нет.', reply_markup=chat_buttons(target, keyboard))
            return
        for row in rows:
            who = 'Вы' if row['sender'] == call.from_user.id else 'Собеседник'
            delivery = {'sent': 'доставлено в Telegram', 'pending': 'доставка не подтверждена', 'failed': 'не доставлено'}[row['status']]
            await call.message.answer(f'<b>{who}</b> · {row["created"]} UTC\n{escape(row["body"])}\n\n<i>{delivery}</i>')
        await call.message.answer('История диалога', reply_markup=keyboard(
            [('Ранее', f'history:{target}:{rows[0]["id"]}')], [('Написать', f'chat:{target}')], [('В меню', 'home')]))

    @router.callback_query(F.data.regexp(r'^unmatch:\d+$'))
    async def unmatch(call: CallbackQuery):
        target = int(call.data.split(':')[1])
        await call.answer()
        await call.message.answer('Завершить знакомство? Совпадение и история переписки в базе будут удалены у обоих. Сообщения в Telegram останутся.',
            reply_markup=keyboard([('Завершить знакомство', f'unmatchconfirm:{target}')], [('Отмена', f'chat:{target}')]))

    @router.callback_query(F.data.regexp(r'^unmatchconfirm:\d+$'))
    async def confirm_unmatch(call: CallbackQuery):
        await store.unmatch(call.from_user.id, int(call.data.split(':')[1]))
        await call.answer('Знакомство завершено')
        await call.message.answer('Совпадение и история удалены из базы.', reply_markup=home)


def chat_buttons(target, keyboard):
    return keyboard([('История', f'history:{target}:9223372036854775807'), ('Выйти', 'chat:leave')],
                    [('Завершить знакомство', f'unmatch:{target}')],
                    [('Пожаловаться', f'report:{target}'), ('Заблокировать', f'block:{target}')])


async def relay_message(message, store, bot, keyboard, home):
    uid = message.from_user.id
    target = await store.chat_target(uid)
    if target is None:
        return False
    if not await store.can_chat(uid, target):
        await store.leave_chat(uid)
        await message.answer('Диалог больше недоступен. Возможно, анкета скрыта или знакомство завершено.', reply_markup=home)
        return True
    text = (message.text or '').strip()
    if not text or len(text) > 2000 or text.startswith('/'):
        await message.answer('В диалоге можно отправлять текст до 2000 символов. Фото и файлы пока не поддерживаются.', reply_markup=chat_buttons(target, keyboard))
        return True
    mid = await store.queue_message(uid, target, text)
    if mid is None:
        await message.answer('Сообщение не отправлено: диалог недоступен.', reply_markup=home)
        return True
    me = await store.profile(uid)
    try:
        await bot.send_message(target, f'<b>Мэтч · {escape(me["name"])}</b>\n\n{escape(text)}',
            reply_markup=keyboard([('Ответить', f'chat:{uid}')],
                                  [('Пожаловаться', f'report:{uid}'), ('Заблокировать', f'block:{uid}')]))
    except DELIVERY_ERRORS:
        await store.message_status(mid, 'failed')
        await message.answer('Не удалось доставить сообщение. Собеседник мог отключить бота, либо Telegram временно недоступен. Сообщение отмечено в истории как недоставленное.', reply_markup=chat_buttons(target, keyboard))
    else:
        await store.message_status(mid, 'sent')
        await message.answer('✓ Доставлено в Telegram', reply_markup=chat_buttons(target, keyboard))
    return True
