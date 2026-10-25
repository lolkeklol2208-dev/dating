import sqlite3
from aiogram.fsm.storage.base import StorageKey
import pytest

from dating.backup import backup
from dating.storage import SQLiteStorage
from dating.store import Store
from tests.test_store import add


async def test_restart_restores_form_chat_history_and_consistent_backup(tmp_path):
    path = str(tmp_path / 'live.sqlite3')
    db = await Store(path).open()
    storage = SQLiteStorage(db)
    key = StorageKey(bot_id=123, chat_id=1, user_id=1)
    await storage.set_state(key, 'Form:age')
    await storage.set_data(key, {'name': 'Анна'})
    await add(db, 1)
    await add(db, 2)
    await db.react(1, 2, 'like')
    await db.react(2, 1, 'like')
    await db.select_chat(1, 2)
    mid = await db.queue_message(1, 2, 'Привет')
    await db.message_status(mid, 'sent')
    output = str(tmp_path / 'backup.sqlite3')
    backup(path, output)  # online WAL backup while the source is still open
    with pytest.raises(ValueError):
        backup(path, output)
    with sqlite3.connect(output) as restored:
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert restored.execute('SELECT body FROM messages').fetchone()[0] == 'Привет'
    await db.close()
    db = await Store(path).open()
    storage = SQLiteStorage(db)
    try:
        assert await storage.get_state(key) == 'Form:age'
        assert (await storage.get_data(key))['name'] == 'Анна'
        assert await db.chat_target(1) == 2
        assert len(await db.history(1, 2)) == 1
        await db.delete(1)
        assert await storage.get_state(key) is None
        assert await storage.get_data(key) == {}
        assert await db.chat_target(1) is None
        assert await db.history(2, 1) == []
    finally:
        await db.close()


async def test_schema_upgrade_keeps_existing_profiles(tmp_path):
    path = str(tmp_path / 'legacy.sqlite3')
    db = await Store(path).open()
    await add(db, 1)
    await db.close()
    with sqlite3.connect(path) as old:
        for table in ('fsm', 'messages', 'conversations', 'report_reviews', 'bans', 'closed_matches'):
            old.execute(f'DROP TABLE {table}')
        old.execute('PRAGMA user_version=0')
    db = await Store(path).open()
    try:
        assert (await db.profile(1))['name'] == 'Анна'
        assert (await db.stats())['messages'] == 0
    finally:
        await db.close()


async def test_backup_rotation_only_removes_owned_old_snapshots(tmp_path):
    from dating.maintenance import rotate_backup
    path = str(tmp_path / 'live.sqlite3')
    db = await Store(path).open()
    try:
        folder = tmp_path / 'copies'
        folder.mkdir()
        unrelated = folder / 'manual-copy.sqlite3'
        unrelated.write_text('preserve user backup')
        for _ in range(4):
            rotate_backup(path, str(folder), keep=2)
        assert len(list(folder.glob('metch-*.sqlite3'))) == 2
        assert unrelated.read_text() == 'preserve user backup'
    finally:
        await db.close()


def test_single_process_lock_releases_after_shutdown(tmp_path):
    from dating.runtime import exclusive_instance
    path = str(tmp_path / 'live.sqlite3')
    with exclusive_instance(path):
        with pytest.raises(RuntimeError):
            with exclusive_instance(path):
                pass
    with exclusive_instance(path):
        pass
