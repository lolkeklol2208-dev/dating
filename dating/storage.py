"""Persistent aiogram form drafts; no Telegram credentials are stored here."""
import json
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.fsm.state import State
from dating.store import Store


class SQLiteStorage(BaseStorage):
    def __init__(self, store: Store):
        self.store = store

    def key(self, key: StorageKey):
        return json.dumps([key.bot_id, key.chat_id, key.user_id, key.thread_id,
                           key.business_connection_id, key.destiny])

    async def set_state(self, key, state=None):
        value = state.state if isinstance(state, State) else state
        async with self.store.transaction():
            await self.store.db.execute('''INSERT INTO fsm(key,user_id,state) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET state=excluded.state''', (self.key(key), key.user_id, value))

    async def get_state(self, key):
        async with self.store.lock:
            row = await self.store._one('SELECT state FROM fsm WHERE key=?', (self.key(key),))
            return row['state'] if row else None

    async def set_data(self, key, data):
        async with self.store.transaction():
            if not data:
                await self.store.db.execute("DELETE FROM fsm WHERE key=? AND state IS NULL", (self.key(key),))
            await self.store.db.execute('''INSERT INTO fsm(key,user_id,data) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET data=excluded.data''',
                (self.key(key), key.user_id, json.dumps(data, ensure_ascii=False)))
            await self.store.db.execute("DELETE FROM fsm WHERE key=? AND state IS NULL AND data='{}'", (self.key(key),))

    async def get_data(self, key):
        async with self.store.lock:
            row = await self.store._one('SELECT data FROM fsm WHERE key=?', (self.key(key),))
            return json.loads(row['data']) if row else {}

    async def close(self):
        pass  # The application owns the shared database connection.
