import time
from collections import OrderedDict, deque
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class AccessMiddleware(BaseMiddleware):
    """Bounded per-user rate limit and server-side global bans."""
    def __init__(self, store, keyboard, limit=25, window=10):
        self.store, self.keyboard = store, keyboard
        self.limit, self.window = limit, window
        self.windows = OrderedDict()

    async def __call__(self, handler, event, data):
        uid = event.from_user.id
        now = time.monotonic()
        recent = self.windows.pop(uid, deque())
        while recent and recent[0] <= now - self.window:
            recent.popleft()
        self.windows[uid] = recent
        if len(self.windows) > 10000:
            self.windows.popitem(last=False)
        if len(recent) >= self.limit:
            # Avoid amplifying message spam; callbacks still need acknowledgment.
            if isinstance(event, CallbackQuery):
                await event.answer('Слишком быстро. Подождите несколько секунд.', show_alert=True)
            return
        recent.append(now)
        if await self.store.is_banned(uid):
            if isinstance(event, CallbackQuery) and event.data in {'delete', 'delete:yes', 'help'}:
                return await handler(event, data)
            if isinstance(event, CallbackQuery):
                await event.answer('Доступ ограничен модератором', show_alert=True)
            else:
                await event.answer('Доступ к знакомствам ограничен модератором. Вы можете удалить свои данные.',
                                   reply_markup=self.keyboard([('Удалить данные', 'delete')], [('Данные и правила', 'help')]))
            return
        # Leaving a screen or issuing a command must not silently keep a
        # previous recipient selected for the user's next text message.
        if isinstance(event, CallbackQuery):
            if not (event.data or '').startswith(('chat:', 'history:', 'unmatch:', 'unmatchconfirm:')):
                await self.store.leave_chat(uid)
        elif (event.text or '').startswith('/'):
            await self.store.leave_chat(uid)
        return await handler(event, data)
