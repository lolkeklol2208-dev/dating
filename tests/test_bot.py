from datetime import datetime, timezone

import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import Chat, Message, Update, User

from dating.bot import caption, make_router
from dating.store import Store
from dating.storage import SQLiteStorage
from tests.test_store import add


class FakeSession(BaseSession):
    """No network: capture actual outgoing Bot API methods."""
    def __init__(self):
        super().__init__()
        self.sent = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, (SendMessage, SendPhoto)):
            return Message(message_id=len(self.sent), date=datetime.now(timezone.utc),
                           chat=Chat(id=int(method.chat_id), type='private'),
                           text=getattr(method, 'text', None))
        return True

    async def stream_content(self, *args, **kwargs):
        yield b''


class Harness:
    def __init__(self, db, admin_id=None):
        self.session = FakeSession()
        self.bot = Bot('123456789:offline-test-token', session=self.session,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher(storage=SQLiteStorage(db), events_isolation=SimpleEventIsolation())
        self.dp.include_router(make_router(db, admin_id))
        self.seq = 0

    async def send(self, uid=1, text=None, callback=None, photo=False, group=False):
        self.seq += 1
        user = User(id=uid, is_bot=False, first_name='Тест', username=f'user{uid}')
        msg = dict(message_id=self.seq, date=0, chat={'id': uid, 'type': 'group' if group else 'private'})
        if callback:
            msg['from'] = {'id': 123456789, 'is_bot': True, 'first_name': 'Bot'}
            update = Update.model_validate({'update_id': self.seq, 'callback_query': {
                'id': str(self.seq), 'from': user.model_dump(), 'chat_instance': 'test',
                'data': callback, 'message': msg}})
        else:
            msg['from'] = user.model_dump()
            if photo:
                msg['photo'] = [{'file_id': 'test-photo', 'file_unique_id': 'unique', 'width': 800, 'height': 800}]
            if text is not None:
                msg['text'] = text
            update = Update.model_validate({'update_id': self.seq, 'message': msg})
        await self.dp.feed_update(self.bot, update)

    def texts(self):
        return '\n'.join(getattr(m, 'text', '') or getattr(m, 'caption', '') or '' for m in self.session.sent)


@pytest_asyncio.fixture
async def app():
    db = await Store(':memory:').open()
    harness = Harness(db)
    yield harness, db
    await harness.dp.storage.close()
    await harness.bot.session.close()
    await db.close()


async def test_registration_validation_and_html(app):
    h, db = app
    await h.send(text='/start')
    assert 'Мне есть 18' in str(h.session.sent[-1].reply_markup)
    await h.send(callback='join')
    await h.send(text='Аня')
    await h.send(text='17')
    assert await db.profile(1) is None
    assert 'с 18 лет' in h.texts()
    await h.send(text='25')
    await h.send(callback='gender:f')
    await h.send(callback='seeking:any')
    await h.send(text='  Москва  ')
    await h.send(text='<b>Люблю</b> музыку & кофе')
    await h.send(text='not a photo')
    assert await db.profile(1) is None
    await h.send(photo=True)
    assert await db.profile(1) is None
    await h.send(callback='publish')
    p = await db.profile(1)
    assert p['age'] == 25 and p['city'] == 'Москва'
    assert '&lt;b&gt;' in caption(p) and '&amp;' in caption(p)
    assert isinstance(h.session.sent[-1], SendPhoto)


async def test_no_contacts_before_match_and_notification_to_both(app):
    h, db = app
    await add(db, 1)
    await add(db, 2)
    await h.send(callback='browse')
    assert 'tg://user' not in h.texts()
    await h.send(callback='like:2')
    assert 'tg://user' not in h.texts()
    await h.send(uid=2, callback='like:1')
    notifications = [m for m in h.session.sent if 'Это взаимно' in (getattr(m, 'text', '') or '')]
    assert len(notifications) == 2
    assert {m.chat_id for m in notifications} == {1, 2}
    await h.send(uid=2, callback='like:1')
    assert len([m for m in h.session.sent if 'Это взаимно' in (getattr(m, 'text', '') or '')]) == 2


async def test_cancel_delete_and_stale_callbacks(app):
    h, db = app
    await h.send(callback='join')
    await h.send(text='Анна')
    await h.send(text='/cancel')
    await h.send(text='25')
    assert await db.profile(1) is None
    await h.send(callback='gender:m')
    assert any(getattr(m, 'show_alert', False) for m in h.session.sent)
    await add(db, 1)
    await h.send(callback='delete')
    assert await db.profile(1) is not None
    await h.send(callback='delete:yes')
    assert await db.profile(1) is None


async def test_group_messages_and_callbacks_ignored(app):
    h, db = app
    await add(db, 1)
    await h.send(text='/start', group=True)
    await h.send(callback='profile', group=True)
    assert h.session.sent == []


async def test_filter_validation_and_pause(app):
    h, db = app
    await add(db, 1)
    await h.send(callback='filters')
    await h.send(text='40 20')
    assert (await db.profile(1))['min_age'] == 18
    await h.send(text='23 35')
    assert (await db.profile(1))['max_age'] == 35
    await h.send(callback='active:0')
    await h.send(callback='browse')
    assert 'Ваша анкета скрыта' in h.texts()
