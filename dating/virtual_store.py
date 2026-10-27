"""Explicitly consented character conversations. No fabricated Telegram accounts."""
from dating.testing_catalog import preview_profile, catalog

CONSENT_VERSION = 1
NOTICE = ('Тестовые знакомства: анкеты вымышлены, мэтч создаётся для проверки приложения. '
          'Ваши сообщения читает администратор сервиса и отвечает от имени персонажа. '
          'Telegram ID, имя и тестовая переписка сохраняются на сервере. '
          'Режим можно выключить с удалением тестовых диалогов.')


def character(profile_id, thread_id=None):
    p = preview_profile(profile_id)
    if not p:
        return None
    p.update(is_virtual=True, character_id=profile_id)
    if thread_id is not None:
        p.update(id=f'v:{thread_id}', thread_id=thread_id)
    return p


def message_row(row, participant):
    return {**{key:row[key] for key in ('id','role','body','created')},
            'sender': participant if row['role']=='participant' else 0, 'status':'sent'}


class VirtualStore:
    async def virtual_state(self, uid):
        async with self.lock:
            row = await self._one('SELECT accepted_at FROM virtual_sessions WHERE uid=? AND version=?', (uid,CONSENT_VERSION))
            return {'enabled': bool(row), 'version': CONSENT_VERSION, 'notice': NOTICE}

    async def virtual_consent(self, uid, name, enabled):
        async with self.transaction():
            if enabled:
                await self.db.execute('''INSERT INTO virtual_sessions(uid,participant_name,version) VALUES (?,?,?)
                    ON CONFLICT(uid) DO UPDATE SET participant_name=excluded.participant_name,version=excluded.version''', (uid,name[:100],CONSENT_VERSION))
            else:
                await self.db.execute('DELETE FROM virtual_sessions WHERE uid=?', (uid,))

    async def _virtual_candidate(self, uid):
        session = await self._one('SELECT turn FROM virtual_sessions WHERE uid=? AND version=?', (uid,CONSENT_VERSION))
        if not session:
            return None
        async with self.db.execute('SELECT character_id FROM virtual_reactions WHERE uid=?', (uid,)) as cursor:
            seen = {r[0] for r in await cursor.fetchall()}
        return next((character(p['id']) for p in catalog()['profiles'] if p['id'] not in seen), None)

    async def virtual_candidate(self, uid):
        async with self.lock:
            return await self._virtual_candidate(uid)

    async def virtual_turn(self, uid, advance=False):
        async with self.transaction():
            if advance:
                await self.db.execute('UPDATE virtual_sessions SET turn=turn+1 WHERE uid=?', (uid,))
            row=await self._one('SELECT turn FROM virtual_sessions WHERE uid=?', (uid,))
            return row['turn'] if row else 0

    async def virtual_react(self, uid, profile_id, kind):
        async with self.transaction():
            candidate=await self._virtual_candidate(uid)
            if not candidate or candidate['character_id']!=profile_id:
                return None
            await self.db.execute('INSERT INTO virtual_reactions(uid,character_id,kind) VALUES (?,?,?)', (uid,profile_id,kind))
            await self.db.execute('UPDATE virtual_sessions SET turn=turn+1 WHERE uid=?', (uid,))
            if kind=='like':
                cursor=await self.db.execute('INSERT INTO virtual_threads(uid,character_id) VALUES (?,?)', (uid,profile_id))
                return cursor.lastrowid
            return 0

    async def virtual_reset_skips(self, uid):
        async with self.transaction():
            await self.db.execute("DELETE FROM virtual_reactions WHERE uid=? AND kind='skip'", (uid,))

    async def _virtual_thread(self, uid, thread_id, operator=False):
        row=await self._one('''SELECT t.*,s.participant_name FROM virtual_threads t JOIN virtual_sessions s ON s.uid=t.uid
            WHERE t.id=? AND s.version=? AND NOT EXISTS (SELECT 1 FROM bans WHERE id=t.uid)''', (thread_id,CONSENT_VERSION))
        return row if row and (operator or row['uid']==uid) else None

    async def _virtual_summary(self, thread, operator=False):
        tid=thread['id']
        last=await self._one('SELECT * FROM virtual_messages WHERE thread_id=? ORDER BY id DESC LIMIT 1', (tid,))
        role='participant' if operator else 'operator'
        read=thread['operator_read'] if operator else thread['participant_read']
        unread=await self._one('SELECT count(*) AS n FROM virtual_messages WHERE thread_id=? AND role=? AND id>?', (tid,role,read))
        return {'last':message_row(last,thread['uid']) if last else None, 'unread':unread['n'],
                'peer_read':thread['participant_read'] if operator else thread['operator_read']}

    async def virtual_threads(self, uid, operator=False, offset=0):
        async with self.lock:
            condition='1=1' if operator else 't.uid=?'
            args=() if operator else (uid,)
            async with self.db.execute('''SELECT t.*,s.participant_name FROM virtual_threads t JOIN virtual_sessions s ON s.uid=t.uid
                WHERE s.version=1 AND NOT EXISTS (SELECT 1 FROM bans WHERE id=t.uid) AND '''+condition+'''
                ORDER BY COALESCE((SELECT max(id) FROM virtual_messages WHERE thread_id=t.id),0) DESC,t.id DESC LIMIT ? OFFSET ?''',
                (*args,21 if operator else 100,offset)) as cursor:
                rows=[dict(r) for r in await cursor.fetchall()]
            more=operator and len(rows)>20
            output=[]
            for row in rows[:20] if operator else rows:
                p=character(row['character_id'],row['id'])
                if not p:
                    continue
                output.append({**p,**await self._virtual_summary(row,operator),
                    **({'participant_name':row['participant_name'],'participant_id':row['uid']} if operator else {})})
            return {'threads':output,'more':bool(more),'unread_total':sum(p['unread'] for p in output)}

    async def virtual_messages(self, uid, thread_id, operator=False, before=None, after=None):
        async with self.lock:
            thread=await self._virtual_thread(uid,thread_id,operator)
            if not thread:
                return None
            condition='id>?' if after is not None else 'id<?'
            bound=after if after is not None else before if before is not None else 2**63-1
            order='ASC' if after is not None else 'DESC'
            async with self.db.execute('SELECT * FROM virtual_messages WHERE thread_id=? AND '+condition+' ORDER BY id '+order+' LIMIT 40',
                (thread_id,bound)) as cursor:
                rows=[message_row(r,thread['uid']) for r in await cursor.fetchall()]
            if after is None:
                rows.reverse()
            return {'messages':rows,'profile':character(thread['character_id'],thread_id),
                    'participant_name':thread['participant_name'] if operator else None,
                    'participant_id':thread['uid'] if operator else None,
                    'summary':await self._virtual_summary(thread,operator),'notice':NOTICE}

    async def virtual_send(self, uid, thread_id, body, nonce, operator=False):
        async with self.transaction():
            thread=await self._virtual_thread(uid,thread_id,operator)
            if not thread:
                return None
            role='operator' if operator else 'participant'
            old=await self._one('SELECT * FROM virtual_messages WHERE thread_id=? AND role=? AND nonce=?', (thread_id,role,nonce))
            if old:
                return {'message':message_row(old,thread['uid']),'participant_id':thread['uid']}
            cursor=await self.db.execute('INSERT INTO virtual_messages(thread_id,role,author,body,nonce) VALUES (?,?,?,?,?)',
                (thread_id,role,uid,body,nonce))
            row=await self._one('SELECT * FROM virtual_messages WHERE id=?', (cursor.lastrowid,))
            return {'message':message_row(row,thread['uid']),'participant_id':thread['uid']}

    async def virtual_read(self, uid, thread_id, last_id, operator=False):
        async with self.transaction():
            thread=await self._virtual_thread(uid,thread_id,operator)
            if not thread:
                return None
            if last_id and not await self._one('SELECT id FROM virtual_messages WHERE thread_id=? AND id=?', (thread_id,last_id)):
                return False
            column='operator_read' if operator else 'participant_read'
            await self.db.execute(f'UPDATE virtual_threads SET {column}=MAX({column},?) WHERE id=?', (last_id,thread_id))
            return thread['uid']

    async def virtual_close(self, uid, thread_id):
        async with self.transaction():
            row=await self._virtual_thread(uid,thread_id)
            if not row:
                return False
            await self.db.execute("UPDATE virtual_reactions SET kind='closed' WHERE uid=? AND character_id=?", (uid,row['character_id']))
            await self.db.execute('DELETE FROM virtual_threads WHERE id=?', (thread_id,))
            return True
