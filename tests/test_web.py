import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
import pytest
import pytest_asyncio

from dating.auth import validate_init_data
from dating.store import Store
from dating.webserver import create_app
from tests.test_store import add

TOKEN = 'local-test-key-not-a-live-telegram-token'


def signed(uid=1, when=None):
    data = {'auth_date': str(int(time.time() if when is None else when)),
            'query_id': 'offline-test', 'user': json.dumps({'id': uid, 'first_name': 'Test', 'username': 'test'})}
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    data['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def headers(uid=1):
    return {'X-Telegram-Init-Data': signed(uid)}


@pytest.mark.parametrize('raw', ['', 'auth_date=1&hash=bad', signed(1, 1), signed(1, time.time()+3600), signed()+'&auth_date=10', signed().replace('Test', 'Hacked')])
def test_auth_rejects_invalid_expired_or_tampered_init_data(raw):
    with pytest.raises(ValueError):
        validate_init_data(raw, TOKEN)


def test_signed_identity_is_server_verified():
    assert validate_init_data(signed(8815384274), TOKEN)['id'] == 8815384274
    with pytest.raises(ValueError):
        validate_init_data(signed(), 'wrong-bot-key')


@pytest_asyncio.fixture
async def webapp():
    db = await Store(':memory:').open()
    bot = SimpleNamespace(send_message=AsyncMock(), send_photo=AsyncMock(return_value=SimpleNamespace(photo=[SimpleNamespace(file_id='uploaded-photo')])) )
    client = TestClient(TestServer(create_app(db, bot, TOKEN, admin_id=99)))
    await client.start_server()
    yield client, db, bot
    await client.close()
    await db.close()


async def test_static_demo_is_public_but_api_requires_signed_auth(webapp):
    c, db, _ = webapp
    assert (await c.get('/')).status == 200
    response = await c.get('/api/me')
    assert response.status == 401
    assert 'Cache-Control' in response.headers
    assert response.headers.get('Access-Control-Allow-Origin') is None
    response = await c.get('/api/me', headers=headers())
    data = await response.json()
    assert data['user']['id'] == 1 and data['profile'] is None
    assert TOKEN not in json.dumps(data)
    assert (await c.get('/assets/app.js')).status == 200
    assert (await c.get('/assets/logo.svg')).status == 200


async def test_entire_api_cycle_match_messenger_read_receipts_and_delete(webapp):
    c, db, bot = webapp
    await add(db, 1)
    await add(db, 2)
    await add(db, 3, city='Тула')
    async def post(path, uid=1, **data):
        return await c.post(path, json=data, headers=headers(uid))
    r = await c.get('/api/candidate', headers=headers())
    p = (await r.json())['profile']
    assert p['id'] == 2 and 'photo' not in p and 'username' not in p
    assert (await (await post('/api/reactions', target=2, kind='like')).json())['match'] is False
    assert (await (await post('/api/reactions', uid=2, target=1, kind='like')).json())['match'] is True
    assert len(await db.pending_notifications(time.time())) == 2
    r = await post('/api/chats/2/messages', body='<hello> & привет', nonce='testnonce0123456789', user_id=3)
    assert r.status == 200
    m = (await r.json())['message']
    assert m['sender'] == 1
    duplicate = await post('/api/chats/2/messages', body='<hello> & привет', nonce='testnonce0123456789')
    assert (await duplicate.json())['message']['id'] == m['id']
    assert len(await db.web_messages(1, 2)) == 1
    summary = await (await c.get('/api/matches', headers=headers(2))).json()
    assert summary['matches'][0]['unread'] == 1
    assert (await c.get('/api/chats/1/messages', headers=headers(3))).status == 409
    assert (await c.get('/api/photos/1', headers=headers(3))).status == 404
    r = await c.get('/api/chats/1/messages', headers=headers(2))
    assert (await r.json())['messages'][0]['body'] == '<hello> & привет'
    assert (await post('/api/chats/1/read', uid=2, last_id=m['id'])).status == 200
    assert (await db.chat_summary(2, 1))['unread'] == 0
    await c.delete('/api/me', headers=headers())
    assert await db.profile(1) is None
    assert await db.pending_notifications(time.time()) == []
    assert await db.web_messages(2, 1) is None
    bot.send_message.assert_not_called()  # delivery worker, not HTTP handlers, owns notifications


async def test_profile_validation_settings_and_no_client_auth_override(webapp):
    c, db, bot = webapp
    await add(db, 1)
    await db.active(1, False)
    original = await db.profile(1)
    data = {**original, 'name': 'Новая анкета', 'id': 999}
    r = await c.post('/api/profile', json=data, headers=headers())
    assert r.status == 200
    assert (await db.profile(1))['name'] == 'Новая анкета'
    assert (await db.profile(1))['active'] == 0
    assert await db.profile(999) is None
    for patch in [{'age':17}, {'name':'x'}, {'gender':'unknown'}, {'bio':'short'}]:
        r = await c.post('/api/profile', json={**data,**patch}, headers=headers())
        assert r.status == 400
    r = await c.post('/api/settings', json={'min_age':40,'max_age':20}, headers=headers())
    assert r.status == 400
    assert (await c.post('/api/settings', json={'active':'true'}, headers=headers())).status == 400
    assert (await c.post('/api/settings', json={'active':True,'min_age':20,'max_age':40}, headers=headers())).status == 200
    bot.send_photo.assert_not_called()


async def test_nonce_cannot_change_content_and_block_closes_api_chat(webapp):
    c, db, _ = webapp
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'like')
    await db.react(2, 1, 'like')
    path='/api/chats/2/messages'
    assert (await c.post(path,json={'body':'hello','nonce':'nonce000000000000'},headers=headers())).status == 200
    assert (await c.post(path,json={'body':'modified','nonce':'nonce000000000000'},headers=headers())).status == 400
    assert (await c.post('/api/actions/block',json={'target':1},headers=headers(2))).status == 200
    assert (await c.post(path,json={'body':'blocked','nonce':'nonce111111111111'},headers=headers())).status == 409


async def test_banned_users_cannot_use_api_but_can_delete_data(webapp):
    c, db, _ = webapp
    await add(db, 1)
    await db.ban(1, 'moderator')
    assert (await c.get('/api/me',headers=headers())).status == 403
    assert (await c.delete('/api/me',headers=headers())).status == 200
    assert await db.profile(1) is None and await db.is_banned(1)


async def test_message_pagination_does_not_lose_large_batches(webapp):
    c, db, _ = webapp
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'like')
    await db.react(2, 1, 'like')
    for n in range(45):
        await db.web_send(1,2,str(n),f'nonce{n:016}')
    first=await (await c.get('/api/chats/1/messages?after=0',headers=headers(2))).json()
    assert len(first['messages']) == 40
    next_page=await (await c.get('/api/chats/1/messages?after='+str(first['messages'][-1]['id']),headers=headers(2))).json()
    assert len(next_page['messages']) == 5
    assert next_page['messages'][0]['id']>first['messages'][-1]['id']


async def test_live_events_are_authenticated_hints_and_read_updates_are_idempotent(webapp):
    import asyncio
    c, db, _ = webapp
    await add(db,1)
    await add(db,2)
    await db.react(1,2,'like')
    await db.react(2,1,'like')
    assert (await c.get('/api/events')).status==401
    stream=await c.get('/api/events',headers=headers(2))
    try:
        assert stream.status==200
        assert await stream.content.readline()==b': connected\n'
        await stream.content.readline()
        r=await c.post('/api/chats/2/messages',json={'body':'PRIVATE BODY','nonce':'sse-test-nonce0001'},headers=headers())
        assert r.status==200
        event=await asyncio.wait_for(stream.content.readline(),timeout=2)
        assert event==b'data: refresh\n' and b'PRIVATE' not in event
        assert await db.read_messages(2,1,1)==1
        assert await db.read_messages(2,1,1)==0
    finally:
        stream.close()


async def test_multipart_upload_requires_valid_image_and_publishes_to_signed_owner(webapp):
    import aiohttp
    c, db, bot = webapp
    fields={'name':'Новая анкета','age':25,'gender':'m','seeking':'any','city':'Москва','bio':'Люблю музыку и прогулки'}
    def upload(payload):
        form=aiohttp.FormData()
        form.add_field('profile',json.dumps(fields))
        form.add_field('photo',payload,filename='photo.png',content_type='image/png')
        return form
    invalid=await c.post('/api/profile',data=upload(b'not an image'),headers=headers(4))
    assert invalid.status==400 and await db.profile(4) is None
    result=await c.post('/api/profile',data=upload(b'\x89PNG\r\n\x1a\n'+b'fake-test-image'),headers=headers(4))
    assert result.status==200
    assert (await db.profile(4))['photo']=='uploaded-photo'
    assert bot.send_photo.call_args.args[0]==4


async def test_unread_badge_includes_chats_beyond_first_page(webapp):
    c,db,_=webapp
    await add(db,1)
    for uid in range(2,8):
        await add(db,uid)
        await db.react(1,uid,'like')
        await db.react(uid,1,'like')
        await db.web_send(uid,1,'Hello',f'unread-test-{uid:016}')
    data=await (await c.get('/api/matches',headers=headers())).json()
    assert len(data['matches'])==5 and data['unread_total']==6
    await db.block(1,2)
    await db.active(3,False)
    assert await db.unread_total(1)==4
