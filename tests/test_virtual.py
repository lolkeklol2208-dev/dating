from dating.store import Store
from tests.test_web import webapp,headers
from tests.test_store import add


async def consent(client,uid=1):
    r=await client.post('/api/virtual/session',json={'enabled':True,'accepted':True,'version':1},headers=headers(uid))
    assert r.status==200


async def match(client,uid=1):
    await consent(client,uid)
    p=(await (await client.get('/api/candidate',headers=headers(uid))).json())['profile']
    r=await client.post('/api/virtual/reactions',json={'target':p['character_id'],'kind':'like'},headers=headers(uid))
    assert r.status==200
    return (await r.json())['thread_id']


async def test_no_virtual_candidates_or_dialogs_without_explicit_own_consent(webapp):
    c,db,_=webapp
    assert (await c.get('/api/virtual/session')).status==401
    state=await (await c.get('/api/virtual/session',headers=headers())).json()
    assert not state['enabled'] and 'администратор' in state['notice'] and 'вымышлены' in state['notice']
    assert (await c.post('/api/virtual/reactions',json={'target':'test-001','kind':'like'},headers=headers())).status==409
    for body in [{'enabled':True},{'enabled':True,'accepted':False,'version':1},{'enabled':True,'accepted':True,'version':True},{'enabled':True,'accepted':True,'version':2},{'enabled':1}]:
        assert (await c.post('/api/virtual/session',json=body,headers=headers())).status==400
    assert not (await db.virtual_state(1))['enabled']
    await consent(c)
    candidate=await (await c.get('/api/candidate',headers=headers())).json()
    assert candidate['profile']['id']=='test-001' and candidate['profile']['is_virtual']
    assert not (await db.virtual_state(2))['enabled']
    assert (await db.stats())['profiles']==0


async def test_main_feed_alternates_real_and_virtual_and_cannot_react_to_stale_card(webapp):
    c,db,_=webapp
    await add(db,1)
    await add(db,2)
    await consent(c)
    assert (await (await c.get('/api/candidate',headers=headers())).json())['profile']['is_virtual']
    assert (await c.post('/api/reactions',json={'target':2,'kind':'like'},headers=headers())).status==409
    tid=await match(c)
    next_card=(await (await c.get('/api/candidate',headers=headers())).json())['profile']
    assert next_card['id']==2 and not next_card.get('is_virtual')
    assert (await c.post('/api/reactions',json={'target':2,'kind':'skip'},headers=headers())).status==200
    assert (await (await c.get('/api/candidate',headers=headers())).json())['profile']['id']=='test-002'
    matches=await (await c.get('/api/matches',headers=headers())).json()
    assert matches['matches']==[] and matches['virtual_matches'][0]['id']==f'v:{tid}'
    assert (await db.stats())['matches']==0


async def test_consented_dialog_operator_reply_dedup_and_access_boundaries(webapp):
    c,db,bot=webapp
    tid=await match(c,1)
    other=await match(c,2)
    user=f'/api/virtual/threads/{tid}'
    admin=f'/api/admin/virtual/threads/{tid}'
    for path in ['/api/admin/virtual/threads',admin+'/messages',admin+'/read']:
        method=c.post if path.endswith('/read') else c.get
        kwargs={'json':{'last_id':0}} if path.endswith('/read') else {}
        assert (await method(path,headers=headers(2),**kwargs)).status==403
    for method,path,kwargs in [(c.get,user+'/messages',{}),(c.post,user+'/messages',{'json':{'body':'leak','nonce':'unauthorized-123456'}}),(c.post,user+'/read',{'json':{'last_id':0}}),(c.delete,user,{})]:
        assert (await method(path,headers=headers(2),**kwargs)).status==409
    msg={'body':'Привет <script>alert(1)</script>','nonce':'participant-message-1','role':'operator','author':99}
    first=await (await c.post(user+'/messages',json=msg,headers=headers())).json()
    duplicate=await (await c.post(user+'/messages',json=msg,headers=headers())).json()
    assert first['message']['id']==duplicate['message']['id'] and first['message']['role']=='participant'
    assert 'author' not in first['message'] and 'nonce' not in first['message']
    inbox=await (await c.get('/api/admin/virtual/threads',headers=headers(99))).json()
    assert len(inbox['threads'])==2 and sum(p['unread'] for p in inbox['threads'])==1
    assert (await c.post(admin+'/read',json={'last_id':first['message']['id']},headers=headers(99))).status==200
    reply={'body':'Привет! Отвечает администратор от имени Ани.','nonce':'operator-message-1','role':'participant'}
    response=await (await c.post(admin+'/messages',json=reply,headers=headers(99))).json()
    assert response['message']['role']=='operator' and response['message']['sender']==0
    data=await (await c.get(user+'/messages',headers=headers())).json()
    assert len(data['messages'])==2 and data['summary']['unread']==1
    assert data['summary']['peer_read']==first['message']['id']
    assert (await c.post(user+'/read',json={'last_id':response['message']['id']},headers=headers())).status==200
    assert (await (await c.get('/api/matches',headers=headers())).json())['virtual_unread_total']==0
    assert (await c.post(f'/api/virtual/threads/{other}/read',json={'last_id':response['message']['id']},headers=headers(2))).status==400
    assert (await db.stats())['messages']==0 and (await db.stats())['matches']==0
    assert await db.pending_notifications(10**15)==[]
    bot.send_message.assert_not_called()


async def test_withdrawal_deletes_test_data_and_keeps_real_conversations(webapp):
    c,db,_=webapp
    await add(db,1)
    await add(db,2)
    await db.react(1,2,'like');await db.react(2,1,'like')
    await db.web_send(1,2,'PRIVATE REAL MESSAGE','real-nonce-123456')
    tid=await match(c)
    await c.post(f'/api/virtual/threads/{tid}/messages',json={'body':'Test only','nonce':'participant-test-123'},headers=headers())
    inbox=await (await c.get('/api/admin/virtual/threads',headers=headers(99))).text()
    assert 'PRIVATE REAL MESSAGE' not in inbox
    assert (await c.get('/api/chats/2/messages',headers=headers(99))).status==409
    assert (await c.post('/api/virtual/session',json={'enabled':False},headers=headers())).status==200
    assert not (await db.virtual_state(1))['enabled']
    for table in ('virtual_sessions','virtual_threads','virtual_messages','virtual_reactions'):
        assert (await db._one(f'SELECT count(*) AS n FROM {table}'))['n']==0
    assert (await c.get(f'/api/admin/virtual/threads/{tid}/messages',headers=headers(99))).status==409
    assert (await db.web_messages(1,2))[0]['body']=='PRIVATE REAL MESSAGE'
    assert (await db.stats())['messages']==1 and await db.can_chat(1,2)


async def test_unmatch_and_profile_deletion_remove_virtual_history(webapp):
    c,db,_=webapp
    tid=await match(c)
    assert (await c.delete(f'/api/virtual/threads/{tid}',headers=headers())).status==200
    assert (await c.post('/api/virtual/reactions',json={'target':'test-001','kind':'like'},headers=headers())).status==409
    assert (await c.get(f'/api/admin/virtual/threads/{tid}/messages',headers=headers(99))).status==409
    tid=await match(c)
    await c.post(f'/api/virtual/threads/{tid}/messages',json={'body':'Remove me','nonce':'delete-nonce-123456'},headers=headers())
    assert (await c.delete('/api/me',headers=headers())).status==200
    assert (await db.virtual_threads(99,True))['threads']==[]
    assert not (await db.virtual_state(1))['enabled']


async def test_ban_hides_consented_threads_and_rejects_operator_delivery(webapp):
    c,db,_=webapp
    tid=await match(c)
    await db.ban(1,'test')
    assert (await c.get('/api/virtual/threads',headers=headers())).status==403
    assert (await (await c.get('/api/admin/virtual/threads',headers=headers(99))).json())['threads']==[]
    assert (await c.post(f'/api/admin/virtual/threads/{tid}/messages',json={'body':'not sent','nonce':'blocked-nonce-12345'},headers=headers(99))).status==409


async def test_restart_keeps_consent_and_messages_without_creating_real_accounts(tmp_path):
    path=str(tmp_path/'app.sqlite3')
    db=await Store(path).open()
    await db.virtual_consent(1,'Участник',True)
    tid=await db.virtual_react(1,'test-001','like')
    await db.virtual_send(1,tid,'Persisted','persistent-nonce-123')
    await db.close()
    db=await Store(path).open()
    try:
        assert (await db.virtual_state(1))['enabled']
        assert (await db.virtual_messages(1,tid))['messages'][0]['body']=='Persisted'
        assert (await db.stats())['profiles']==0
        assert not await db.needs_bootstrap()
    finally:
        await db.close()


async def test_virtual_history_pages_without_gaps_and_operator_list_is_bounded(webapp):
    c,db,_=webapp
    tid=await match(c)
    for n in range(45):
        await db.virtual_send(1,tid,f'Message {n}',f'history-nonce-{n:016}')
    latest=await (await c.get(f'/api/virtual/threads/{tid}/messages',headers=headers())).json()
    assert len(latest['messages'])==40 and latest['messages'][0]['body']=='Message 5'
    first_id=latest['messages'][0]['id']
    older=await (await c.get(f'/api/virtual/threads/{tid}/messages?before={first_id}',headers=headers())).json()
    assert [m['body'] for m in older['messages']]==[f'Message {n}' for n in range(5)]
    cursor=latest['messages'][-1]['id']
    await db.virtual_send(99,tid,'New reply','last-reply-nonce-123456',True)
    fresh=await (await c.get(f'/api/virtual/threads/{tid}/messages?after={cursor}',headers=headers())).json()
    assert [m['body'] for m in fresh['messages']]==['New reply']
    for uid in range(100,120):
        await db.virtual_consent(uid,f'Participant {uid}',True)
        await db.virtual_react(uid,'test-001','like')
    first=await (await c.get('/api/admin/virtual/threads',headers=headers(99))).json()
    second=await (await c.get('/api/admin/virtual/threads?offset=20',headers=headers(99))).json()
    assert len(first['threads'])==20 and first['more']
    assert len(second['threads'])==1 and not second['more']
    assert len({p['thread_id'] for p in first['threads']+second['threads']})==21
