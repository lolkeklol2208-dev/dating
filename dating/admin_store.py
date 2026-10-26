"""Moderation queries and atomic decisions; never expose private message bodies."""


class ModerationConflict(Exception):
    pass


class AdminStore:
    async def admin_overview(self):
        async with self.lock:
            return await self._one('''SELECT
                (SELECT count(*) FROM profiles) AS profiles,
                (SELECT count(*) FROM profiles p WHERE active=1
                    AND NOT EXISTS (SELECT 1 FROM bans b WHERE b.id=p.id)) AS visible,
                (SELECT count(*) FROM profiles WHERE active=0) AS hidden,
                (SELECT count(*) FROM matches) AS matches,
                (SELECT count(*) FROM messages) AS messages,
                (SELECT count(*) FROM bans) AS bans,
                (SELECT count(*) FROM reports r LEFT JOIN report_reviews v
                    ON v.actor=r.actor AND v.target=r.target WHERE v.action IS NULL) AS reports_open,
                (SELECT count(*) FROM report_reviews) AS reports_reviewed''')

    async def admin_users(self, query='', status='all', offset=0, limit=20):
        conditions = {
            'all': '1=1', 'visible': 'p.active=1 AND b.id IS NULL',
            'hidden': 'p.active=0 AND b.id IS NULL', 'banned': 'b.id IS NOT NULL',
        }
        where = conditions[status]
        args = []
        if query:
            where += ''' AND (CAST(u.id AS TEXT)=? OR instr(casefold(
                COALESCE(p.name,'') || ' ' || COALESCE(p.username,'') || ' ' || COALESCE(p.city,'')),?)>0)'''
            args = [query.lstrip('@'), query.lstrip('@').casefold()]
        base = ''' FROM (SELECT id FROM profiles UNION SELECT id FROM bans) u
            LEFT JOIN profiles p ON p.id=u.id LEFT JOIN bans b ON b.id=u.id WHERE ''' + where
        async with self.lock:
            total = (await self._one('SELECT count(*) AS n' + base, args))['n']
            async with self.db.execute('''SELECT u.id,p.name,p.username,p.age,p.city,p.active,
                b.reason AS ban_reason,b.created AS banned_at''' + base + ' ORDER BY u.id DESC LIMIT ? OFFSET ?',
                (*args, limit, offset)) as cursor:
                return {'users': [dict(r) for r in await cursor.fetchall()], 'total': total,
                        'more': offset + limit < total}

    async def admin_user(self, uid):
        async with self.lock:
            profile = await self._one('SELECT * FROM profiles WHERE id=?', (uid,))
            ban = await self._one('SELECT reason,created FROM bans WHERE id=?', (uid,))
            if not profile and not ban:
                return None
            counts = await self._one('''SELECT
                (SELECT count(*) FROM matches WHERE a=? OR b=?) AS matches,
                (SELECT count(*) FROM reports WHERE target=?) AS reports_received''', (uid, uid, uid))
            return {'id': uid, 'profile': profile, 'ban': ban, **counts}

    async def admin_reports(self, status='open', offset=0, limit=20):
        condition = 'v.action IS NULL' if status == 'open' else 'v.action IS NOT NULL'
        base = ''' FROM reports r JOIN profiles p ON p.id=r.target
            JOIN profiles a ON a.id=r.actor LEFT JOIN report_reviews v
            ON v.actor=r.actor AND v.target=r.target WHERE ''' + condition
        async with self.lock:
            total = (await self._one('SELECT count(*) AS n' + base))['n']
            async with self.db.execute('''SELECT r.*,p.name AS target_name,a.name AS actor_name,
                v.action,(SELECT count(*) FROM bans WHERE id=r.target) AS banned''' + base +
                ' ORDER BY r.created, r.actor, r.target LIMIT ? OFFSET ?', (limit, offset)) as cursor:
                return {'reports': [dict(r) for r in await cursor.fetchall()], 'total': total,
                        'more': offset + limit < total}

    async def admin_audit(self, offset=0, limit=20):
        async with self.lock:
            total = (await self._one('SELECT count(*) AS n FROM moderation_audit'))['n']
            async with self.db.execute('''SELECT * FROM moderation_audit
                ORDER BY id DESC LIMIT ? OFFSET ?''', (limit, offset)) as cursor:
                return {'entries': [dict(r) for r in await cursor.fetchall()], 'total': total,
                        'more': offset + limit < total}

    async def moderate(self, moderator, target, action, reason, report_actor=None):
        """Decision, report status, ban and audit commit together or not at all."""
        if action not in {'ban', 'unban', 'dismiss'} or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 300:
            raise ValueError('Укажите причину от 3 до 300 символов')
        if action == 'ban' and moderator == target:
            raise ValueError('Нельзя заблокировать собственный аккаунт администратора')
        if action == 'dismiss' and report_actor is None:
            raise ValueError('Выберите жалобу')
        if action == 'unban' and report_actor is not None:
            raise ValueError('Разблокировка выполняется из карточки пользователя')
        async with self.transaction():
            if report_actor is not None:
                report = await self._one('''SELECT r.actor,v.action FROM reports r LEFT JOIN report_reviews v
                    ON v.actor=r.actor AND v.target=r.target WHERE r.actor=? AND r.target=?''', (report_actor, target))
                if not report or report['action'] is not None:
                    raise ModerationConflict('Жалоба уже обработана или удалена. Обновите список.')
            banned = await self._one('SELECT id FROM bans WHERE id=?', (target,))
            if action == 'ban':
                if not await self._one('SELECT id FROM profiles WHERE id=?', (target,)):
                    raise ModerationConflict('Анкета уже удалена')
                if banned and report_actor is None:
                    raise ModerationConflict('Пользователь уже заблокирован')
                if not banned:
                    await self.db.execute('INSERT INTO bans(id,reason) VALUES (?,?)', (target, reason.strip()))
                await self.db.execute('DELETE FROM conversations WHERE actor=? OR target=?', (target, target))
            elif action == 'unban':
                if not banned:
                    raise ModerationConflict('Блокировка уже снята')
                await self.db.execute('DELETE FROM bans WHERE id=?', (target,))
            if report_actor is not None:
                await self.db.execute('INSERT INTO report_reviews(actor,target,action) VALUES (?,?,?)',
                    (report_actor, target, 'banned' if action == 'ban' else 'dismissed'))
            await self.db.execute('''INSERT INTO moderation_audit(moderator,target,action,reason,report_actor)
                VALUES (?,?,?,?,?)''', (moderator, target, action, reason.strip(), report_actor))
