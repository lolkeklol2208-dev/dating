import asyncio
import hashlib
from pathlib import Path
import sqlite3
import struct

from dating.store import Store
from dating.testing_catalog import catalog
from tests.test_web import webapp, headers
from tests.test_store import add


def test_exactly_100_adult_fictional_profiles_have_unique_texts_and_generated_portraits():
    data = catalog()
    assert len(data['profiles']) == 100
    assert len({p['id'] for p in data['profiles']}) == 100
    assert len({p['bio'] for p in data['profiles']}) == 100
    assert {p['age'] for p in data['profiles']} == set(range(20,31))
    assert all(p['is_test'] and p['gender'] == 'f' and len(p['tags']) >= 2 and 10 <= len(p['bio']) <= 500 for p in data['profiles'])
    hashes=set()
    portraits=set()
    for p in data['profiles']:
        photo=p['photo']
        portraits.add((photo['url'],photo['column'],photo['row']))
        path=Path(__file__).parents[1]/'dating'/'web'/photo['url'].removeprefix('/assets/')
        image=path.read_bytes()
        assert image[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II',image[16:24]) == (1536,1024)
        hashes.add(hashlib.sha256(image).hexdigest())
    assert len(hashes)==10 and len(portraits)==100


async def test_testing_catalog_is_owner_only_and_isolated_from_real_matching(webapp):
    client, db, bot=webapp
    for path in ['', '/export', '/test-001']:
        assert (await client.get('/api/admin/test-profiles'+path)).status==401
        assert (await client.get('/api/admin/test-profiles'+path,headers=headers(1))).status==403
    assert (await client.post('/api/admin/test-profiles/test-001',json={'notes':'test'},headers=headers(1))).status==403
    page=await (await client.get('/api/admin/test-profiles',headers=headers(99))).json()
    assert page['total']==page['summary']['total']==100 and len(page['profiles'])==20 and page['more']
    assert all(p['is_test'] for p in page['profiles']) and page['notice']
    await add(db,1)
    assert await db.candidate(1) is None
    assert (await db.stats())['profiles']==1
    assert await db.matches(1)==[]
    assert await db.pending_notifications(10**15)==[]
    assert (await client.post('/api/reactions',json={'target':'test-001','kind':'like'},headers=headers(1))).status==400
    assert (await client.post('/api/chats/test-001/messages',json={'body':'Hello','nonce':'test-nonce-123456'},headers=headers(1))).status==400
    bot.send_message.assert_not_called()


async def test_filtering_and_pagination_visit_every_fixture_without_duplicates(webapp):
    client,_,_=webapp
    ids=[]
    for offset in range(0,100,20):
        page=await (await client.get('/api/admin/test-profiles',params={'offset':offset},headers=headers(99))).json()
        ids += [p['id'] for p in page['profiles']]
        assert page['more'] == (offset < 80)
    assert len(ids)==len(set(ids))==100
    page=await (await client.get('/api/admin/test-profiles',params={'q':'НАДЯ','city':'Москва','min_age':24,'max_age':24},headers=headers(99))).json()
    assert page['total']==1 and page['profiles'][0]['id']=='test-011'
    assert (await client.get('/api/admin/test-profiles?min_age=30&max_age=20',headers=headers(99))).status==400
    assert (await client.get('/api/admin/test-profiles?min_age=19',headers=headers(99))).status==400
    assert (await client.get('/api/admin/test-profiles?status=published',headers=headers(99))).status==400


async def test_reviews_are_saved_once_conflicts_do_not_overwrite_and_export_contains_all_100(webapp):
    client,db,_=webapp
    body={'rating':4,'status':'needs_work','notes':'=HYPERLINK("example") <text>','revision':0}
    responses=await asyncio.gather(*(client.post('/api/admin/test-profiles/test-001',json=body,headers=headers(99)) for _ in range(2)))
    assert sorted(r.status for r in responses)==[200,409]
    detail=await (await client.get('/api/admin/test-profiles/test-001',headers=headers(99))).json()
    assert detail['profile']['review']['revision']==1 and detail['profile']['review']['rating']==4
    assert detail['profile']['review']['notes']==body['notes']
    changed={**body,'notes':'Новая заметка','status':'reviewed','revision':1}
    assert (await client.post('/api/admin/test-profiles/test-001',json=changed,headers=headers(99))).status==200
    exported=await (await client.get('/api/admin/test-profiles/export',headers=headers(99))).json()
    assert len(exported['profiles'])==100 and not exported['more']
    assert exported['summary']=={'total':100,'new':99,'reviewed':1,'needs_work':0}
    assert exported['profiles'][0]['review']['notes']=='Новая заметка'
    assert (await db.stats())['profiles']==0
    assert not await db.needs_bootstrap()  # notes alone are data and must not be overwritten
    for invalid in [{**changed,'rating':True},{**changed,'rating':6},{**changed,'notes':'x'*2001},{**changed,'status':'published'}]:
        assert (await client.post('/api/admin/test-profiles/test-001',json=invalid,headers=headers(99))).status==400
    assert (await client.get('/api/admin/test-profiles/missing',headers=headers(99))).status==404


async def test_v5_upgrade_restart_preserves_notes_profiles_and_no_fixture_accounts(tmp_path):
    path=str(tmp_path/'app.sqlite3')
    db=await Store(path).open()
    await add(db,1)
    await db.close()
    with sqlite3.connect(path) as old:
        old.execute('DROP TABLE test_profile_reviews')
        old.execute('PRAGMA user_version=5')
    db=await Store(path).open()
    await db.review_testing_profile('test-100',5,'reviewed','Проверено на телефоне',0)
    await db.close()
    db=await Store(path).open()
    try:
        assert (await db.testing_profile('test-100'))['review']['notes']=='Проверено на телефоне'
        assert (await db.stats())['profiles']==1 and (await db.profile(1))['name']=='Анна'
        assert (await db.testing_profile('test-001'))['review']['status']=='new'
    finally:
        await db.close()
