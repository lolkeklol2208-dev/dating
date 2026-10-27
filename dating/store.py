from __future__ import annotations

import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from dating.admin_store import AdminStore
from dating.testing_catalog import TestingCatalogStore
from dating.virtual_store import VirtualStore


class Store(AdminStore, TestingCatalogStore, VirtualStore):
    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()

    async def open(self):
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.create_function('casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
        await self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY, username TEXT, name TEXT NOT NULL,
                age INTEGER NOT NULL CHECK(age BETWEEN 18 AND 99),
                gender TEXT NOT NULL CHECK(gender IN ('m','f')),
                seeking TEXT NOT NULL CHECK(seeking IN ('m','f','any')),
                city TEXT NOT NULL, city_key TEXT NOT NULL, bio TEXT NOT NULL,
                photo TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                min_age INTEGER NOT NULL DEFAULT 18, max_age INTEGER NOT NULL DEFAULT 99
            );
            CREATE TABLE IF NOT EXISTS reactions (
                actor INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                target INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('like','skip')),
                PRIMARY KEY(actor,target), CHECK(actor != target)
            );
            CREATE TABLE IF NOT EXISTS matches (
                a INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                b INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(a,b), CHECK(a < b)
            );
            CREATE TABLE IF NOT EXISTS blocks (
                actor INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                target INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                PRIMARY KEY(actor,target), CHECK(actor != target)
            );
            CREATE TABLE IF NOT EXISTS reports (
                actor INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                target INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                reason TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(actor,target)
            );
            CREATE TABLE IF NOT EXISTS closed_matches (
                a INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                b INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                PRIMARY KEY(a,b)
            );
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY, reason TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS report_reviews (
                actor INTEGER NOT NULL, target INTEGER NOT NULL, action TEXT NOT NULL,
                PRIMARY KEY(actor,target),
                FOREIGN KEY(actor,target) REFERENCES reports(actor,target) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS conversations (
                actor INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
                target INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                a INTEGER NOT NULL, b INTEGER NOT NULL, sender INTEGER NOT NULL,
                body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(a,b) REFERENCES matches(a,b) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS fsm (
                key TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                state TEXT, data TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS message_keys (
                actor INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                nonce TEXT NOT NULL,
                message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                PRIMARY KEY(actor,nonce)
            );
            CREATE TABLE IF NOT EXISTS message_reads (
                actor INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                target INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                last_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(actor,target)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                sender INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, dedup TEXT UNIQUE NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_try REAL NOT NULL DEFAULT 0,
                done INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS deployment_state (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS moderation_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moderator INTEGER NOT NULL, target INTEGER NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('ban','unban','dismiss')),
                reason TEXT NOT NULL, report_actor INTEGER,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS test_profile_reviews (
                profile_id TEXT PRIMARY KEY,
                rating INTEGER NOT NULL DEFAULT 0 CHECK(rating BETWEEN 0 AND 5),
                status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','reviewed','needs_work')),
                notes TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1,
                updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS virtual_sessions (
                uid INTEGER PRIMARY KEY, participant_name TEXT NOT NULL, version INTEGER NOT NULL,
                accepted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, turn INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS virtual_reactions (
                uid INTEGER NOT NULL REFERENCES virtual_sessions(uid) ON DELETE CASCADE,
                character_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('like','skip','closed')),
                PRIMARY KEY(uid,character_id)
            );
            CREATE TABLE IF NOT EXISTS virtual_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL REFERENCES virtual_sessions(uid) ON DELETE CASCADE,
                character_id TEXT NOT NULL, participant_read INTEGER NOT NULL DEFAULT 0,
                operator_read INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(uid,character_id)
            );
            CREATE TABLE IF NOT EXISTS virtual_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL REFERENCES virtual_threads(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('participant','operator')), author INTEGER NOT NULL,
                body TEXT NOT NULL, nonce TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(thread_id,role,nonce)
            );
            CREATE INDEX IF NOT EXISTS virtual_messages_thread ON virtual_messages(thread_id,id);
            PRAGMA user_version=7;
            CREATE INDEX IF NOT EXISTS notifications_pending ON notifications(done,next_try);
            CREATE INDEX IF NOT EXISTS messages_pair ON messages(a,b,id);
            CREATE INDEX IF NOT EXISTS profiles_search ON profiles(city_key, active, age);
        ''')
        return self

    async def close(self):
        await self.db.close()

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            try:
                yield
                await self.db.commit()
            except BaseException:
                await self.db.rollback()
                raise

    async def _one(self, sql, args=()):
        async with self.db.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def profile(self, uid):
        async with self.lock:
            return await self._one('SELECT * FROM profiles WHERE id=?', (uid,))

    async def save(self, uid, username, data):
        async with self.transaction():
            await self.db.execute('''INSERT INTO profiles
                (id,username,name,age,gender,seeking,city,city_key,bio,photo)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                username=excluded.username,name=excluded.name,age=excluded.age,
                gender=excluded.gender,seeking=excluded.seeking,city=excluded.city,
                city_key=excluded.city_key,bio=excluded.bio,photo=excluded.photo''',
                (uid, username, data['name'], data['age'], data['gender'], data['seeking'],
                 data['city'], data['city'].casefold().replace('ё', 'е'), data['bio'], data['photo']))

    async def update_username(self, uid, username):
        async with self.transaction():
            await self.db.execute('UPDATE profiles SET username=? WHERE id=?', (username, uid))

    async def active(self, uid, value):
        async with self.transaction():
            await self.db.execute('UPDATE profiles SET active=? WHERE id=?', (int(value), uid))

    async def filters(self, uid, low, high):
        async with self.transaction():
            await self.db.execute('UPDATE profiles SET min_age=?,max_age=? WHERE id=?', (low, high, uid))

    async def delete(self, uid):
        async with self.transaction():
            await self.db.execute('DELETE FROM virtual_sessions WHERE uid=?', (uid,))
            await self.db.execute('DELETE FROM profiles WHERE id=?', (uid,))
            await self.db.execute('DELETE FROM fsm WHERE user_id=?', (uid,))

    async def candidate(self, uid):
        async with self.lock:
            return await self._one('''SELECT p.* FROM profiles p JOIN profiles me ON me.id=?
                WHERE p.id != me.id AND me.active=1 AND p.active=1
                AND NOT EXISTS (SELECT 1 FROM bans WHERE id IN (p.id,me.id))
                AND p.city_key=me.city_key AND p.age BETWEEN me.min_age AND me.max_age
                AND me.age BETWEEN p.min_age AND p.max_age
                AND (me.seeking='any' OR me.seeking=p.gender)
                AND (p.seeking='any' OR p.seeking=me.gender)
                AND NOT EXISTS (SELECT 1 FROM blocks WHERE
                    (actor=me.id AND target=p.id) OR (actor=p.id AND target=me.id))
                AND NOT EXISTS (SELECT 1 FROM reactions WHERE actor=me.id AND target=p.id)
                ORDER BY p.id LIMIT 1''', (uid,))

    async def react(self, uid, target, kind, notify=False):
        """Return None for unavailable target, False for no new match, True for new match."""
        if uid == target or kind not in ('like', 'skip'):
            return None
        async with self.transaction():
            a, b = sorted((uid, target))
            if await self._one('SELECT a FROM closed_matches WHERE a=? AND b=?', (a, b)):
                return None
            available = await self._one('''SELECT p.id FROM profiles p JOIN profiles me ON me.id=?
                WHERE p.id=? AND p.active=1 AND me.active=1
                AND NOT EXISTS (SELECT 1 FROM bans WHERE id IN (p.id,me.id))
                AND NOT EXISTS (SELECT 1 FROM blocks WHERE
                    (actor=? AND target=?) OR (actor=? AND target=?))''',
                (uid, target, uid, target, target, uid))
            if not available:
                return None
            await self.db.execute('INSERT OR IGNORE INTO reactions VALUES (?,?,?)', (uid, target, kind))
            own = await self._one('SELECT kind FROM reactions WHERE actor=? AND target=?', (uid, target))
            reverse = await self._one('SELECT kind FROM reactions WHERE actor=? AND target=?', (target, uid))
            if own['kind'] == 'like' and reverse and reverse['kind'] == 'like':
                a, b = sorted((uid, target))
                cursor = await self.db.execute('INSERT OR IGNORE INTO matches(a,b) VALUES (?,?)', (a, b))
                created = cursor.rowcount == 1
                if created and notify:
                    for recipient, sender in ((uid, target), (target, uid)):
                        await self.db.execute("INSERT OR IGNORE INTO notifications(recipient,sender,kind,dedup) VALUES (?,?,'match',?)",
                            (recipient, sender, f'match:{a}:{b}:{recipient}'))
                return created
            return False

    async def block(self, uid, target, reason=None):
        if uid == target:
            return
        async with self.transaction():
            if not await self._one('SELECT id FROM profiles WHERE id=?', (uid,)):
                return
            if not await self._one('SELECT id FROM profiles WHERE id=?', (target,)):
                return
            await self.db.execute('INSERT OR IGNORE INTO blocks VALUES (?,?)', (uid, target))
            if reason:
                await self.db.execute('INSERT OR IGNORE INTO reports(actor,target,reason) VALUES (?,?,?)',
                                      (uid, target, reason))

    async def matches(self, uid, offset=0):
        async with self.lock:
            async with self.db.execute('''SELECT p.* FROM matches m JOIN profiles p
                ON p.id=CASE WHEN m.a=? THEN m.b ELSE m.a END
                WHERE (m.a=? OR m.b=?) AND p.active=1
                AND NOT EXISTS (SELECT 1 FROM bans WHERE id IN (m.a,m.b))
                AND NOT EXISTS (SELECT 1 FROM blocks WHERE
                    (actor=? AND target=p.id) OR (actor=p.id AND target=?))
                ORDER BY m.created DESC, p.id LIMIT 5 OFFSET ?''',
                (uid, uid, uid, uid, uid, offset)) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def reset_skips(self, uid):
        async with self.transaction():
            await self.db.execute("DELETE FROM reactions WHERE actor=? AND kind='skip'", (uid,))

    async def is_banned(self, uid):
        async with self.lock:
            return bool(await self._one('SELECT id FROM bans WHERE id=?', (uid,)))

    async def ban(self, uid, reason):
        async with self.transaction():
            await self.db.execute('INSERT OR REPLACE INTO bans(id,reason) VALUES (?,?)', (uid, reason))
            await self.db.execute('DELETE FROM conversations WHERE actor=? OR target=?', (uid, uid))

    async def unban(self, uid):
        async with self.transaction():
            await self.db.execute('DELETE FROM bans WHERE id=?', (uid,))

    async def reports(self):
        async with self.lock:
            async with self.db.execute('''SELECT r.*, p.name FROM reports r
                JOIN profiles p ON p.id=r.target
                LEFT JOIN report_reviews v ON v.actor=r.actor AND v.target=r.target
                WHERE v.action IS NULL ORDER BY r.created LIMIT 10''') as cursor:
                return [dict(r) for r in await cursor.fetchall()]

    async def review(self, actor, target, action):
        async with self.transaction():
            await self.db.execute('''INSERT OR REPLACE INTO report_reviews(actor,target,action)
                SELECT actor,target,? FROM reports WHERE actor=? AND target=?''', (action, actor, target))

    async def stats(self):
        async with self.lock:
            result = {}
            for table in ('profiles', 'matches', 'messages', 'reports', 'bans'):
                result[table] = (await self._one(f'SELECT count(*) AS n FROM {table}'))['n']
            return result

    async def _can_chat(self, uid, target):
        a, b = sorted((uid, target))
        return bool(await self._one('''SELECT m.a FROM matches m
            JOIN profiles p ON p.id=? JOIN profiles q ON q.id=?
            WHERE m.a=? AND m.b=? AND p.active=1 AND q.active=1
            AND NOT EXISTS (SELECT 1 FROM bans WHERE id IN (?,?))
            AND NOT EXISTS (SELECT 1 FROM blocks WHERE
                (actor=? AND target=?) OR (actor=? AND target=?))''',
            (uid, target, a, b, uid, target, uid, target, target, uid)))

    async def can_chat(self, uid, target):
        async with self.lock:
            return await self._can_chat(uid, target)

    async def select_chat(self, uid, target):
        async with self.transaction():
            if not await self._can_chat(uid, target):
                return False
            await self.db.execute('INSERT OR REPLACE INTO conversations VALUES (?,?)', (uid, target))
            return True

    async def leave_chat(self, uid):
        async with self.transaction():
            await self.db.execute('DELETE FROM conversations WHERE actor=?', (uid,))

    async def chat_target(self, uid):
        async with self.lock:
            row = await self._one('SELECT target FROM conversations WHERE actor=?', (uid,))
            return row['target'] if row else None

    async def queue_message(self, uid, target, text):
        if not text.strip() or len(text) > 2000:
            return None
        async with self.transaction():
            if not await self._can_chat(uid, target):
                return None
            a, b = sorted((uid, target))
            cursor = await self.db.execute('INSERT INTO messages(a,b,sender,body) VALUES (?,?,?,?)',
                                           (a, b, uid, text))
            return cursor.lastrowid

    async def message_status(self, mid, status):
        if status not in {'sent', 'failed'}:
            raise ValueError('Invalid message status')
        async with self.transaction():
            await self.db.execute('UPDATE messages SET status=? WHERE id=?', (status, mid))

    async def history(self, uid, target, before=9223372036854775807):
        async with self.lock:
            if not await self._can_chat(uid, target):
                return []
            a, b = sorted((uid, target))
            async with self.db.execute('''SELECT * FROM messages WHERE a=? AND b=? AND id<?
                AND (status='sent' OR sender=?) ORDER BY id DESC LIMIT 5''', (a, b, before, uid)) as cursor:
                return [dict(row) for row in await cursor.fetchall()][::-1]

    async def unmatch(self, uid, target):
        async with self.transaction():
            a, b = sorted((uid, target))
            await self.db.execute('INSERT OR IGNORE INTO closed_matches SELECT a,b FROM matches WHERE a=? AND b=?', (a, b))
            await self.db.execute('DELETE FROM matches WHERE a=? AND b=?', (a, b))
            await self.db.execute('DELETE FROM conversations WHERE (actor=? AND target=?) OR (actor=? AND target=?)',
                                  (uid, target, target, uid))

    async def web_messages(self, uid, target, before=None, after=None):
        async with self.lock:
            if not await self._can_chat(uid, target):
                return None
            a, b = sorted((uid, target))
            query = 'SELECT * FROM messages WHERE a=? AND b=? AND (status=\'sent\' OR sender=?)'
            args = [a, b, uid]
            if after is not None:
                query += ' AND id>? ORDER BY id ASC LIMIT 40'
                args.append(after)
            else:
                query += ' AND id<? ORDER BY id DESC LIMIT 40'
                args.append(before or 9223372036854775807)
            async with self.db.execute(query, args) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]
            return rows if after is not None else rows[::-1]

    async def web_send(self, uid, target, text, nonce):
        async with self.transaction():
            if not await self._can_chat(uid, target):
                return None
            previous = await self._one('''SELECT m.* FROM message_keys k JOIN messages m ON m.id=k.message_id
                WHERE k.actor=? AND k.nonce=?''', (uid, nonce))
            if previous:
                if {previous['a'], previous['b']} != {uid, target} or previous['body'] != text:
                    raise ValueError('Повторный идентификатор сообщения с другим содержимым')
                return previous
            a, b = sorted((uid, target))
            cursor = await self.db.execute("INSERT INTO messages(a,b,sender,body,status) VALUES (?,?,?,?,'sent')",
                                           (a, b, uid, text))
            mid = cursor.lastrowid
            await self.db.execute('INSERT INTO message_keys VALUES (?,?,?)', (uid, nonce, mid))
            await self.db.execute("INSERT INTO notifications(recipient,sender,kind,dedup) VALUES (?,?,'message',?)",
                                  (target, uid, f'message:{mid}'))
            return await self._one('SELECT * FROM messages WHERE id=?', (mid,))

    async def read_messages(self, uid, target, last_id):
        async with self.transaction():
            if not await self._can_chat(uid, target):
                return None
            latest = await self._one('SELECT MAX(id) AS n FROM messages WHERE a=? AND b=?', tuple(sorted((uid, target))))
            last_id = min(last_id, latest['n'] or 0)
            previous = await self._one('SELECT last_id FROM message_reads WHERE actor=? AND target=?', (uid, target))
            if previous and previous['last_id'] >= last_id:
                return 0
            await self.db.execute('''INSERT INTO message_reads VALUES (?,?,?) ON CONFLICT(actor,target)
                DO UPDATE SET last_id=MAX(last_id,excluded.last_id)''', (uid, target, last_id))
            return True

    async def chat_summary(self, uid, target):
        async with self.lock:
            a, b = sorted((uid, target))
            last = await self._one("SELECT * FROM messages WHERE a=? AND b=? AND status='sent' ORDER BY id DESC LIMIT 1", (a, b))
            unread = await self._one('''SELECT count(*) AS n FROM messages WHERE a=? AND b=? AND sender=? AND status='sent'
                AND id>COALESCE((SELECT last_id FROM message_reads WHERE actor=? AND target=?),0)''',
                (a, b, target, uid, target))
            peer_read = await self._one('SELECT last_id FROM message_reads WHERE actor=? AND target=?', (target, uid))
            return {'last': last, 'unread': unread['n'], 'peer_read': peer_read['last_id'] if peer_read else 0}

    async def pending_notifications(self, now):
        async with self.lock:
            async with self.db.execute('SELECT * FROM notifications WHERE done=0 AND next_try<=? ORDER BY id LIMIT 20', (now,)) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def finish_notification(self, nid, done, next_try=0):
        async with self.transaction():
            await self.db.execute('UPDATE notifications SET attempts=attempts+1,done=?,next_try=? WHERE id=?', (int(done), next_try, nid))

    async def unread_total(self, uid):
        async with self.lock:
            row = await self._one('''SELECT count(*) AS n FROM messages m
                JOIN profiles me ON me.id=? JOIN profiles peer ON peer.id=m.sender
                WHERE m.sender!=? AND (m.a=? OR m.b=?) AND m.status='sent'
                AND me.active=1 AND peer.active=1
                AND NOT EXISTS (SELECT 1 FROM bans WHERE id IN (me.id,peer.id))
                AND NOT EXISTS (SELECT 1 FROM blocks WHERE
                    (actor=me.id AND target=peer.id) OR (actor=peer.id AND target=me.id))
                AND m.id>COALESCE((SELECT last_id FROM message_reads WHERE actor=me.id AND target=peer.id),0)''',
                (uid, uid, uid, uid))
            return row['n']


    async def needs_bootstrap(self):
        async with self.lock:
            marker=await self._one("SELECT value FROM deployment_state WHERE key='bootstrap'")
            if marker:
                return False
            # Never treat an existing populated database as an empty target.
            for table in ('profiles','fsm','bans','messages','moderation_audit','test_profile_reviews','virtual_sessions'):
                row=await self._one(f'SELECT count(*) AS n FROM {table}')
                if row['n']:
                    return False
            return True

    async def import_snapshot(self, staged):
        from dating.deployment import BootstrapError, validate_snapshot
        await asyncio.to_thread(validate_snapshot,staged)
        async with self.lock:
            for table in ('profiles','fsm','bans','messages','deployment_state','moderation_audit','test_profile_reviews','virtual_sessions'):
                row=await self._one(f'SELECT count(*) AS n FROM {table}')
                if row['n']:
                    raise BootstrapError('Целевая база уже содержит данные; замена запрещена')
            if self.path==':memory:':
                raise BootstrapError('Для импорта нужен постоянный диск')
            await self.db.close()
            old=Path(self.path+'.before-bootstrap')
            shutil.copy2(self.path,old)
            try:
                os.replace(staged,self.path)
                await self.open()
                await self.db.execute("INSERT INTO deployment_state VALUES ('bootstrap','imported')")
                await self.db.commit()
            except BaseException:
                try:
                    await self.db.close()
                finally:
                    for suffix in ('-wal','-shm'):
                        Path(self.path+suffix).unlink(missing_ok=True)
                    os.replace(old,self.path)
                    await self.open()
                raise
            old.unlink(missing_ok=True)
