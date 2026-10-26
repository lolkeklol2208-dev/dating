import asyncio
import sqlite3

from aiohttp.test_utils import TestClient, TestServer
import pytest

from dating.store import Store
from dating.webserver import create_app
from tests.test_store import add
from tests.test_web import webapp, headers, TOKEN


@pytest.mark.parametrize('path', ['/overview','/users','/users/1','/reports','/audit','/moderate'])
async def test_admin_endpoints_reject_anonymous_and_non_owner_even_with_spoofed_role(webapp, path):
    client, db, _ = webapp
    method = client.post if path == '/moderate' else client.get
    kwargs = {'json': {'target': 2, 'action': 'ban', 'reason': 'test', 'admin_id': 99}} if path == '/moderate' else {}
    assert (await method('/api/admin'+path, **kwargs)).status == 401
    assert (await method('/api/admin'+path, headers={**headers(1), 'X-Admin-ID': '99'}, **kwargs)).status == 403
    assert (await db.admin_audit())['total'] == 0
    assert not await db.is_banned(2)


async def test_capability_requires_configured_owner_and_does_not_require_a_dating_profile(webapp):
    client, _, _ = webapp
    me = await (await client.get('/api/me', headers=headers(99))).json()
    assert me['user']['is_admin'] and me['profile'] is None
    me = await (await client.get('/api/me', headers=headers(1))).json()
    assert not me['user']['is_admin']
    assert (await client.get('/api/admin/overview', headers=headers(99))).status == 200
    db = await Store(':memory:').open()
    try:
        async with TestClient(TestServer(create_app(db, None, TOKEN))) as no_owner:
            assert (await no_owner.get('/api/admin/overview', headers=headers(99))).status == 403
    finally:
        await db.close()


async def test_admin_search_unicode_literal_wildcards_pagination_and_deleted_bans(webapp):
    client, db, _ = webapp
    for uid in range(1, 24):
        await add(db, uid, name='Алёна' if uid == 1 else 'Анна')
    await db.active(2, False)
    await db.ban(3, 'legacy reason')
    async def users(**params):
        return await (await client.get('/api/admin/users', params=params, headers=headers(99))).json()
    first = await users()
    second = await users(offset=20)
    assert len(first['users']) == 20 and first['more'] and first['total'] == 23
    assert len(second['users']) == 3 and not second['more']
    assert not {p['id'] for p in first['users']} & {p['id'] for p in second['users']}
    assert [p['id'] for p in (await users(q='АЛЁНА'))['users']] == [1]
    assert [p['id'] for p in (await users(q='@user1'))['users']]  # username search
    assert (await users(q="%' OR 1=1 --"))['total'] == 0
    assert (await users(status='hidden'))['total'] == 1
    assert (await users(status='visible'))['total'] == 21
    await db.delete(3)
    assert (await users(status='banned'))['users'][0]['name'] is None
    detail = await (await client.get('/api/admin/users/3', headers=headers(99))).json()
    assert detail['profile'] is None and detail['ban']['reason'] == 'legacy reason'


async def test_report_decision_is_atomic_audited_and_only_applied_once(webapp):
    client, db, _ = webapp
    for uid in (1, 2, 3):
        await add(db, uid)
    await db.react(2, 3, 'like')
    await db.react(3, 2, 'like')
    await db.web_send(2, 3, 'private conversation body', 'admin-private-test')
    await db.block(1, 2, 'spam')
    reports = await (await client.get('/api/admin/reports', headers=headers(99))).json()
    assert reports['total'] == 1
    body = {'target': 2, 'report_actor': 1, 'action': 'ban', 'reason': 'Подтверждённый спам'}
    responses = await asyncio.gather(*(client.post('/api/admin/moderate', json=body, headers=headers(99)) for _ in range(2)))
    assert sorted(r.status for r in responses) == [200, 409]
    assert await db.is_banned(2) and not await db.can_chat(2, 3)
    assert (await client.get('/api/me', headers=headers(2))).status == 403
    assert (await client.get('/api/chats/2/messages', headers=headers(99))).status == 409
    summary = await (await client.get('/api/admin/overview', headers=headers(99))).json()
    assert summary['reports_open'] == 0 and summary['reports_reviewed'] == 1 and summary['bans'] == 1
    audit = await (await client.get('/api/admin/audit', headers=headers(99))).json()
    assert audit['total'] == 1 and audit['entries'][0]['moderator'] == 99
    detail = await (await client.get('/api/admin/users/2', headers=headers(99))).text()
    assert 'private conversation body' not in detail
    assert 'photo-id' not in detail
    assert (await db.admin_reports('reviewed'))['reports'][0]['action'] == 'banned'
    await db.delete(2)
    assert (await db.admin_audit())['total'] == 1  # minimal record survives profile removal
    response = await client.post('/api/admin/moderate', json={'target': 2, 'action': 'unban', 'reason': 'Апелляция принята'}, headers=headers(99))
    assert response.status == 200 and not await db.is_banned(2)
    assert (await db.admin_audit())['total'] == 2


async def test_dismiss_keeps_personal_block_and_invalid_decisions_change_nothing(webapp):
    client, db, _ = webapp
    for uid in (1, 2, 99):
        await add(db, uid)
    await db.block(1, 2, 'content')
    async def decide(**body):
        return await client.post('/api/admin/moderate', json=body, headers=headers(99))
    assert (await decide(target=99, action='ban', reason='self ban')).status == 400
    assert (await decide(target=2, action='ban', reason='')).status == 400
    assert (await decide(target=2, action='unknown', reason='invalid')).status == 400
    assert (await decide(target=True, action='ban', reason='invalid')).status == 400
    assert (await decide(target=2, action='dismiss', reason='invalid')).status == 400
    assert (await decide(target=2, report_actor=99, action='ban', reason='missing report')).status == 409
    assert not await db.is_banned(99) and not await db.is_banned(2)
    assert (await db.admin_audit())['total'] == 0
    assert (await decide(target=2, report_actor=1, action='dismiss', reason='Нарушение не подтверждено')).status == 200
    assert (await db.candidate(1))['id'] != 2 and not await db.is_banned(2)
    assert (await db.admin_audit())['entries'][0]['action'] == 'dismiss'


async def test_additive_upgrade_and_restart_preserve_profile_ban_and_audit(tmp_path):
    path = str(tmp_path / 'legacy-v4.sqlite3')
    db = await Store(path).open()
    await add(db, 1)
    await db.close()
    with sqlite3.connect(path) as legacy:
        legacy.execute('DROP TABLE moderation_audit')
        legacy.execute('PRAGMA user_version=4')
    db = await Store(path).open()
    await db.moderate(99, 1, 'ban', 'Проверка миграции')
    await db.close()
    db = await Store(path).open()
    try:
        assert await db.is_banned(1) and (await db.profile(1))['name'] == 'Анна'
        assert (await db.admin_audit())['total'] == 1
    finally:
        await db.close()
