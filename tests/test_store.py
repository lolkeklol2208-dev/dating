import asyncio

import pytest
import pytest_asyncio

from dating.store import Store


def profile(**updates):
    return dict(name='Анна', age=25, gender='f', seeking='any', city='Москва',
                bio='Кофе, музыка и прогулки', photo='photo-id', **updates)


async def add(db, uid, **updates):
    data = profile()
    data.update(updates)
    await db.save(uid, f'user{uid}', data)


@pytest_asyncio.fixture
async def db():
    store = await Store(':memory:').open()
    yield store
    await store.close()


async def test_search_is_mutual_and_city_normalized(db):
    await add(db, 1, gender='m', seeking='f', city='Орёл')
    await add(db, 2, city='орел', seeking='f')  # excludes men
    await add(db, 3, city='орел', seeking='m')
    await add(db, 4, city='Тула')
    assert (await db.candidate(1))['id'] == 3
    await db.filters(3, 30, 40)
    assert await db.candidate(1) is None
    await db.filters(3, 18, 99)
    await db.filters(1, 30, 40)
    assert await db.candidate(1) is None


async def test_like_privacy_and_exactly_one_match(db):
    await add(db, 1)
    await add(db, 2)
    assert await db.react(1, 2, 'like') is False
    assert await db.matches(1) == []
    results = await asyncio.gather(*(db.react(2, 1, 'like') for _ in range(5)))
    assert results.count(True) == 1
    assert [p['id'] for p in await db.matches(1)] == [2]
    assert [p['id'] for p in await db.matches(2)] == [1]
    assert await db.candidate(1) is None


async def test_skip_cannot_be_turned_into_like_by_stale_button(db):
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'skip')
    await db.react(2, 1, 'like')
    assert await db.react(1, 2, 'like') is False
    assert await db.matches(1) == []


@pytest.mark.parametrize('report', [None, 'spam'])
async def test_block_hides_both_directions_and_existing_match(db, report):
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'like')
    await db.react(2, 1, 'like')
    await db.block(1, 2, report)
    assert await db.matches(1) == await db.matches(2) == []
    assert await db.candidate(1) is None
    assert await db.candidate(2) is None
    assert await db.react(2, 1, 'like') is None


async def test_hidden_and_missing_profiles(db):
    await add(db, 1)
    await add(db, 2)
    await db.active(2, False)
    assert await db.candidate(1) is None
    assert await db.react(1, 2, 'like') is None
    assert await db.react(1, 999, 'like') is None
    assert await db.react(1, 1, 'like') is None


async def test_edit_keeps_visibility_filters_and_relations(db):
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'like')
    await db.filters(1, 20, 40)
    await db.active(1, False)
    await add(db, 1, name='Новое имя')
    p = await db.profile(1)
    assert p['name'] == 'Новое имя'
    assert (p['active'], p['min_age'], p['max_age']) == (0, 20, 40)
    await db.active(1, True)
    assert await db.react(2, 1, 'like') is True


async def test_persistence_and_cascade_deletion(tmp_path):
    path = str(tmp_path / 'db.sqlite3')
    db = await Store(path).open()
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'like')
    await db.react(2, 1, 'like')
    await db.block(1, 2, 'spam')
    await db.close()
    db = await Store(path).open()
    try:
        assert (await db.profile(1))['name'] == 'Анна'
        await db.delete(1)
        assert await db.profile(1) is None
        assert await db.profile(2) is not None
        for table in ('reactions', 'matches', 'blocks', 'reports'):
            async with db.db.execute(f'SELECT count(*) FROM {table}') as cursor:
                assert (await cursor.fetchone())[0] == 0
    finally:
        await db.close()
