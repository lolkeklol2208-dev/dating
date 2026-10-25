import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from tests.test_bot import Harness, app  # reuse the complete Bot API harness
from tests.test_store import add


async def pair(db):
    await add(db, 1)
    await add(db, 2, name='Дима')
    await db.react(1, 2, 'like')
    await db.react(2, 1, 'like')


async def test_full_chat_cycle_and_safe_navigation(app):
    h, db = app
    await pair(db)
    await h.send(callback='chat:2')
    await h.send(text='Привет <Дима> & как дела?')
    rows = await db.history(2, 1)
    assert len(rows) == 1 and rows[0]['status'] == 'sent'
    delivered = [m for m in h.session.sent if isinstance(m, SendMessage) and m.chat_id == 2]
    assert '&lt;Дима&gt; &amp;' in delivered[-1].text
    assert 'tg://user' not in delivered[-1].text
    await h.send(uid=2, callback='chat:1')
    await h.send(uid=2, text='Привет!')
    assert len(await db.history(1, 2)) == 2
    await h.send(callback='history:2:9223372036854775807')
    assert 'История диалога' in h.texts()
    await h.send(callback='home')
    await h.send(text='Это не собеседнику')
    assert len(await db.history(1, 2)) == 2
    await h.send(callback='chat:2')
    await h.send(text='/help')
    assert await db.chat_target(1) is None


async def test_cannot_chat_without_match_or_after_block(app):
    h, db = app
    await add(db, 1)
    await add(db, 2)
    await h.send(callback='chat:2')
    assert await db.chat_target(1) is None
    await pair(db)
    await h.send(callback='chat:2')
    await h.send(uid=2, callback='block:1')
    await h.send(text='Должно не отправиться')
    assert await db.chat_target(1) is None
    assert await db.history(1, 2) == []


async def test_delivery_failure_is_explicit_and_hidden_from_recipient(app):
    h, db = app
    await pair(db)
    await h.send(callback='chat:2')
    original = h.session.make_request

    async def fail(bot, method, timeout=None):
        if isinstance(method, SendMessage) and method.chat_id == 2:
            raise TelegramForbiddenError(method=method, message='bot blocked')
        return await original(bot, method, timeout)

    h.session.make_request = fail
    await h.send(text='Недоставленное сообщение')
    assert (await db.history(1, 2))[0]['status'] == 'failed'
    assert await db.history(2, 1) == []
    assert 'Не удалось доставить' in h.texts()


async def test_unmatch_removes_history_and_cannot_be_undone_by_old_like(app):
    h, db = app
    await pair(db)
    await h.send(callback='chat:2')
    await h.send(text='Привет')
    await h.send(callback='unmatch:2')
    assert await db.can_chat(1, 2)
    await h.send(callback='unmatchconfirm:2')
    assert not await db.can_chat(1, 2)
    assert await db.history(1, 2) == []
    assert await db.react(1, 2, 'like') is None
    async with db.db.execute('SELECT count(*) FROM messages') as c:
        assert (await c.fetchone())[0] == 0


async def test_moderation_requires_owner_and_ban_survives_profile_deletion(app):
    h, db = app
    await pair(db)
    await db.block(1, 2, 'spam')
    await h.send(callback='modconfirm:1:2')
    assert not await db.is_banned(2)
    owner = Harness(db, admin_id=99)
    try:
        await owner.send(uid=99, text='/admin')
        assert 'Модерация' in owner.texts()
        await owner.send(uid=99, callback='admin:reports')
        assert 'Жалоба' in owner.texts()
        await owner.send(uid=99, callback='modconfirm:1:2')
        assert await db.is_banned(2)
        assert await db.reports() == []
        await h.send(uid=2, callback='join')
        assert 'Доступ ограничен' in str(h.session.sent[-1])
        await h.send(uid=2, callback='delete:yes')
        assert await db.profile(2) is None
        assert await db.is_banned(2)
        await owner.send(uid=99, text='/unban 2')
        assert not await db.is_banned(2)
    finally:
        await owner.dp.storage.close()
        await owner.bot.session.close()


async def test_unsupported_content_and_self_chat(app):
    h, db = app
    await pair(db)
    await h.send(callback='chat:1')
    assert await db.chat_target(1) is None
    await h.send(callback='chat:2')
    await h.send(photo=True)
    assert await db.history(1, 2) == []
    await h.send(text='x' * 2001)
    assert await db.history(1, 2) == []


async def test_delete_during_wizard_does_not_become_profile_field(app):
    h, db = app
    await h.send(callback='join')
    await h.send(text='/delete')
    assert 'Удалить анкету и черновики' in h.texts()
    await h.send(callback='delete:yes')
    assert await h.dp.fsm.get_context(bot=h.bot, chat_id=1, user_id=1).get_state() is None


async def test_reset_only_skips_and_preserves_likes(app):
    h, db = app
    await pair(db)
    await add(db, 3)
    await db.react(1, 3, 'skip')
    assert await db.candidate(1) is None
    await h.send(callback='reset:yes')
    assert (await db.candidate(1))['id'] == 3
    assert [p['id'] for p in await db.matches(1)] == [2]


async def test_history_is_private_to_participants(app):
    h, db = app
    await pair(db)
    mid = await db.queue_message(1, 2, 'Приватное сообщение')
    await db.message_status(mid, 'sent')
    await add(db, 3)
    assert await db.history(3, 1) == []
    await h.send(uid=3, callback='history:1:9223372036854775807')
    assert 'Приватное сообщение' not in h.texts()


async def test_rate_limit_has_bounded_bursts_and_recovers(app, monkeypatch):
    h, db = app
    now = [100.0]
    monkeypatch.setattr('dating.middleware.time.monotonic', lambda: now[0])
    for _ in range(28):
        await h.send(callback='home')
    assert any('Слишком быстро' in (getattr(m, 'text', '') or '') for m in h.session.sent)
    before = len(h.session.sent)
    now[0] += 11
    await h.send(text='/id')
    assert len(h.session.sent) > before
    assert 'Ваш Telegram ID' in h.texts()
