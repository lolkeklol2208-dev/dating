"""Fictional testing fixtures, isolated from Telegram accounts and real matching."""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from dating.admin_store import ModerationConflict


@lru_cache(maxsize=1)
def catalog():
    data = json.loads((Path(__file__).with_name('web') / 'test-profiles.json').read_text())
    profiles = data['profiles']
    if len(profiles) != 100 or len({p['id'] for p in profiles}) != 100:
        raise ValueError('Тестовый каталог должен содержать 100 уникальных анкет')
    if not all(p['is_test'] and p['gender'] == 'f' and 20 <= p['age'] <= 30 for p in profiles):
        raise ValueError('Неверные параметры тестового каталога')
    return data


def default_review():
    return {'rating': 0, 'status': 'new', 'notes': '', 'revision': 0, 'updated': None}


class TestingCatalogStore:
    async def testing_profiles(self, query='', city='', low=20, high=30, status='all', offset=0, limit=20):
        async with self.lock:
            async with self.db.execute('SELECT * FROM test_profile_reviews') as cursor:
                reviews = {r['profile_id']: dict(r) for r in await cursor.fetchall()}
        data = catalog()
        rows = deepcopy(data['profiles'])
        for row in rows:
            row['review'] = reviews.get(row['id'], default_review())
            row['review'].pop('profile_id', None)
        counts = Counter(p['review']['status'] for p in rows)
        summary = {'total': len(rows), 'new': counts['new'], 'reviewed': counts['reviewed'], 'needs_work': counts['needs_work']}
        query = query.casefold()
        selected = [p for p in rows if low <= p['age'] <= high
                    and (not city or p['city'].casefold() == city.casefold())
                    and (status == 'all' or p['review']['status'] == status)
                    and (not query or query in ' '.join((p['name'], p['occupation'], p['bio'], *p['tags'])).casefold())]
        return {'profiles': selected[offset:offset+limit], 'total': len(selected),
                'more': offset+limit < len(selected), 'summary': summary,
                'cities': sorted({p['city'] for p in rows}), 'notice': data['notice']}

    async def testing_profile(self, profile_id):
        profile = next((p for p in catalog()['profiles'] if p['id'] == profile_id), None)
        if not profile:
            return None
        async with self.lock:
            review = await self._one('SELECT * FROM test_profile_reviews WHERE profile_id=?', (profile_id,))
        result = deepcopy(profile)
        result['review'] = review or default_review()
        result['review'].pop('profile_id', None)
        return result

    async def review_testing_profile(self, profile_id, rating, status, notes, revision):
        if not any(p['id'] == profile_id for p in catalog()['profiles']):
            raise ValueError('Тестовая анкета не найдена')
        async with self.transaction():
            previous = await self._one('SELECT revision FROM test_profile_reviews WHERE profile_id=?', (profile_id,))
            if (previous['revision'] if previous else 0) != revision:
                raise ModerationConflict('Заметка уже изменена в другом окне. Закройте карточку и откройте её снова.')
            await self.db.execute('''INSERT INTO test_profile_reviews(profile_id,rating,status,notes,revision)
                VALUES (?,?,?,?,1) ON CONFLICT(profile_id) DO UPDATE SET rating=excluded.rating,
                status=excluded.status,notes=excluded.notes,revision=test_profile_reviews.revision+1,
                updated=CURRENT_TIMESTAMP''', (profile_id, rating, status, notes))
