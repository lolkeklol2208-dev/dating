from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage

from dating.notifications import deliver_once
from tests.test_store import db, add


async def test_durable_notifications_retry_and_do_not_duplicate_success(db):
    await add(db,1)
    await add(db,2)
    await db.react(1,2,'like',notify=True)
    await db.react(2,1,'like',notify=True)
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=TelegramNetworkError(method=SendMessage(chat_id=1,text='test'),message='offline')))
    await deliver_once(db,bot,'https://example.com')
    queued=await db.pending_notifications(time.time()+100)
    assert len(queued)==2 and all(n['attempts']==1 for n in queued)
    async with db.transaction():
        await db.db.execute('UPDATE notifications SET next_try=0')
    bot.send_message=AsyncMock()
    await deliver_once(db,bot,'https://example.com')
    assert bot.send_message.call_count==2
    assert not await db.pending_notifications(time.time()+100)
    await deliver_once(db,bot,'https://example.com')
    assert bot.send_message.call_count==2


async def test_block_cancels_queued_notifications(db):
    await add(db,1)
    await add(db,2)
    await db.react(1,2,'like')
    await db.react(2,1,'like',notify=True)
    await db.block(1,2)
    bot=SimpleNamespace(send_message=AsyncMock())
    await deliver_once(db,bot,'https://example.com')
    bot.send_message.assert_not_called()
