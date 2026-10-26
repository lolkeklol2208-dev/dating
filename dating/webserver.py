"""Same-origin Mini App API, authenticated exclusively by signed Telegram initData."""
import asyncio
import hashlib
from collections import OrderedDict, deque
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import os
import tempfile
import time

from aiohttp import web
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from dating.auth import validate_init_data
from dating.admin_api import register_admin
from dating.deployment import BootstrapError, MAX_SNAPSHOT, verify_import_headers, service_proof

ROOT = Path(__file__).with_name('web')
API = web.AppKey('api', object)


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def number(value, minimum=1, maximum=2**53-1):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise ApiError(400, 'Ожидалось целое число')
    result = int(value)
    if not minimum <= result <= maximum:
        raise ApiError(400, 'Число вне допустимого диапазона')
    return result


def public_profile(p, own=False):
    if not p:
        return None
    fields = ['id', 'name', 'age', 'city', 'bio']
    if own:
        fields += ['gender', 'seeking', 'active', 'min_age', 'max_age']
    return {**{key: p[key] for key in fields}, 'photo_url': f'/api/photos/{p["id"]}?v={hashlib.sha256(p["photo"].encode()).hexdigest()[:12]}'}


@web.middleware
async def boundary(request, handler):
    try:
        if request.path.startswith('/api/') and request.path not in {'/api/deploy/import','/api/deploy/challenge'}:
            service = request.app[API]
            if service.bootstrap_pending:
                raise ApiError(503,'Идёт безопасный перенос базы. Попробуйте открыть приложение позже.')
            try:
                request['user'] = validate_init_data(request.headers.get('X-Telegram-Init-Data', ''), service.token)
            except (ValueError, TypeError, json.JSONDecodeError):
                raise ApiError(401, 'Откройте Мэтч через Telegram. Если сессия истекла — закройте и откройте приложение.')
            uid = request['user']['id']
            service.limit(uid)
            if await service.store.is_banned(uid) and not (request.path == '/api/me' and request.method == 'DELETE'):
                raise ApiError(403, 'Доступ ограничен модератором. Удаление данных доступно в боте через /delete.')
        response = await handler(request)
    except ApiError as exc:
        response = web.json_response({'error': exc.message}, status=exc.status)
    except web.HTTPException as exc:
        response = web.json_response({'error': 'Запрос не выполнен'}, status=exc.status) if request.path.startswith('/api/') else exc
    except (ValueError, json.JSONDecodeError, KeyError, TypeError):
        response = web.json_response({'error': 'Проверьте заполненные поля'}, status=400)
    except TelegramAPIError:
        response = web.json_response({'error': 'Telegram временно недоступен. Попробуйте позже.'}, status=502)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else 'no-cache'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' blob: data:; connect-src 'self'; "
        "font-src 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
        "base-uri 'self'; form-action 'self'; object-src 'none'")
    return response


class Service:
    def __init__(self, store, bot, token, admin_id=None, bootstrap=False, public_url=None):
        self.public_url = public_url
        self.store, self.bot, self.token, self.admin_id = store, bot, token, admin_id
        self.windows = OrderedDict()
        self.writes = asyncio.Lock()
        self.listeners = {}
        self.bootstrap_pending = bootstrap
        self.ready = asyncio.Event()
        self.bootstrap_lock = asyncio.Lock()
        if not bootstrap:
            self.ready.set()

    async def deployment_challenge(self, req):
        if not self.bootstrap_pending or not self.public_url:
            raise ApiError(404,'Первичный импорт закрыт')
        nonce=req.query.get('nonce','')
        if not re.fullmatch(r'[0-9a-f]{64}',nonce):
            raise ApiError(400,'Неверный запрос проверки сервиса')
        return web.json_response({'url':self.public_url,'proof':service_proof(self.token,self.public_url,nonce)})

    async def import_database(self, req):
        if not self.bootstrap_pending:
            raise ApiError(404,'Первичный импорт закрыт')
        stamp=req.headers.get('X-Metch-Time','')
        digest=req.headers.get('X-Metch-SHA256','')
        signature=req.headers.get('X-Metch-Signature','')
        if not verify_import_headers(self.token,stamp,digest,signature):
            raise ApiError(403,'Импорт не авторизован')
        if req.content_length and req.content_length>MAX_SNAPSHOT:
            raise ApiError(413,'Резервная копия слишком большая')
        async with self.bootstrap_lock:
            if not self.bootstrap_pending:
                raise ApiError(404,'Первичный импорт уже выполнен')
            directory=Path(self.store.path).resolve().parent
            fd,temporary=tempfile.mkstemp(prefix='.import-',dir=directory)
            path=Path(temporary)
            try:
                size=0
                checksum=hashlib.sha256()
                with os.fdopen(fd,'wb') as file:
                    async for chunk in req.content.iter_chunked(65536):
                        size+=len(chunk)
                        if size>MAX_SNAPSHOT:
                            raise ApiError(413,'Резервная копия слишком большая')
                        checksum.update(chunk)
                        file.write(chunk)
                import hmac
                if not hmac.compare_digest(checksum.hexdigest(),digest):
                    raise ApiError(400,'Контрольная сумма базы не совпадает')
                try:
                    await self.store.import_snapshot(path)
                except BootstrapError as exc:
                    raise ApiError(409,str(exc))
                self.bootstrap_pending=False
                self.ready.set()
                return web.json_response({'ok':True,'stats':await self.store.stats()})
            finally:
                path.unlink(missing_ok=True)
                for suffix in ('-wal','-shm'):
                    Path(str(path)+suffix).unlink(missing_ok=True)

    def publish(self, *users):
        for uid in users:
            for queue in self.listeners.get(uid, set()):
                if not queue.full():
                    queue.put_nowait(True)

    async def events(self, req):
        uid = req['user']['id']
        current = self.listeners.setdefault(uid, set())
        if len(current) >= 2 or sum(map(len, self.listeners.values())) >= 1024:
            raise ApiError(429, 'Слишком много открытых окон')
        queue = asyncio.Queue(maxsize=8)
        current.add(queue)
        stream = web.StreamResponse(headers={'Content-Type':'text/event-stream', 'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})
        await stream.prepare(req)
        last_beat = time.monotonic()
        try:
            await stream.write(b': connected\n\n')
            while req.transport and not req.transport.is_closing():
                try:
                    await asyncio.wait_for(queue.get(), timeout=1)
                    await stream.write(b'data: refresh\n\n')
                except asyncio.TimeoutError:
                    if time.monotonic() - last_beat > 15:
                        await stream.write(b': heartbeat\n\n')
                        last_beat = time.monotonic()
        except (ConnectionError, RuntimeError):
            pass
        finally:
            current.discard(queue)
            if not current:
                self.listeners.pop(uid, None)
        return stream

    def limit(self, uid):
        now = time.monotonic()
        window = self.windows.pop(uid, deque())
        while window and window[0] < now - 60:
            window.popleft()
        self.windows[uid] = window
        if len(self.windows) > 10000:
            self.windows.popitem(last=False)
        if len(window) >= 180:
            raise ApiError(429, 'Слишком много запросов. Подождите немного.')
        window.append(now)

    async def visible(self, uid, target):
        if uid == target or uid == self.admin_id:
            return await self.store.profile(target)
        if await self.store.can_chat(uid, target):
            return await self.store.profile(target)
        candidate = await self.store.candidate(uid)
        return candidate if candidate and candidate['id'] == target else None

    async def me(self, req):
        uid = req['user']['id']
        if req.method == 'DELETE':
            await self.store.delete(uid)
            return web.json_response({'ok': True})
        await self.store.update_username(uid, req['user'].get('username'))
        return web.json_response({'user': {'id': uid, 'first_name': req['user'].get('first_name', ''),
                                         'is_admin': bool(self.admin_id and uid == self.admin_id)},
                                 'profile': public_profile(await self.store.profile(uid), own=True)})

    async def profile(self, req):
        uid = req['user']['id']
        old = await self.store.profile(uid)
        photo = None
        if req.content_type == 'application/json':
            data = await req.json()
        else:
            if req.content_length and req.content_length > 6 * 1024 * 1024:
                raise ApiError(413, 'Фото слишком большое')
            reader = await req.multipart()
            data = None
            seen = set()
            async def read_part(part, maximum):
                chunks, size = [], 0
                while chunk := await part.read_chunk(65536):
                    size += len(chunk)
                    if size > maximum:
                        raise ApiError(413, 'Фото или анкета слишком большого размера')
                    chunks.append(chunk)
                return b''.join(chunks)
            while part := await reader.next():
                if part.name not in {'profile', 'photo'} or part.name in seen:
                    raise ApiError(400, 'Неверные поля загрузки')
                seen.add(part.name)
                if part.name == 'profile':
                    raw = await read_part(part, 16384)
                    if len(raw) > 16384:
                        raise ApiError(400, 'Слишком большая анкета')
                    data = json.loads(raw)
                elif part.name == 'photo':
                    photo = await read_part(part, 5 * 1024 * 1024)
            if data is None:
                raise ApiError(400, 'Анкета не передана')
        if not isinstance(data, dict):
            raise ApiError(400, 'Анкета должна содержать поля')
        for field, low, high in [('name', 2, 30), ('city', 2, 60), ('bio', 10, 500)]:
            value = data.get(field)
            if not isinstance(value, str):
                raise ApiError(400, 'Заполните имя, город и описание')
            data[field] = ' '.join(value.split())
            if not low <= len(data[field]) <= high:
                raise ApiError(400, f'{field}: от {low} до {high} символов')
        if not any(c.isalpha() for c in data['city']):
            raise ApiError(400, 'Укажите название города')
        data['age'] = number(data.get('age'), 18, 99)
        if data.get('gender') not in {'m', 'f'} or data.get('seeking') not in {'m', 'f', 'any'}:
            raise ApiError(400, 'Выберите пол и предпочтения')
        if photo:
            valid = photo.startswith(b'\xff\xd8\xff') or photo.startswith(b'\x89PNG\r\n\x1a\n') or (photo[:4] == b'RIFF' and photo[8:12] == b'WEBP')
            if len(photo) > 5 * 1024 * 1024 or not valid:
                raise ApiError(400, 'Нужно фото JPG, PNG или WEBP до 5 МБ')
            try:
                sent = await self.bot.send_photo(uid, BufferedInputFile(photo, filename='profile.jpg'), caption='💜 Фото вашей анкеты в Мэтч')
            except TelegramAPIError:
                raise ApiError(409, 'Не удалось загрузить фото. Откройте бота, нажмите Start и попробуйте JPG или PNG.')
            data['photo'] = sent.photo[-1].file_id
        elif old:
            data['photo'] = old['photo']
        else:
            raise ApiError(400, 'Добавьте фото анкеты')
        await self.store.save(uid, req['user'].get('username'), data)
        return web.json_response({'profile': public_profile(await self.store.profile(uid), own=True)})

    async def get_profile(self, req):
        p = await self.visible(req["user"]["id"], number(req.match_info["target"]))
        if not p:
            raise ApiError(404, "Анкета недоступна")
        return web.json_response({"profile": public_profile(p)})

    async def photo(self, req):
        p = await self.visible(req['user']['id'], number(req.match_info['target']))
        if not p:
            raise ApiError(404, 'Фото недоступно')
        file = await self.bot.get_file(p['photo'])
        if not file.file_path or (file.file_size or 0) > 20 * 1024 * 1024:
            raise ApiError(404, 'Фото недоступно')
        buffer = BytesIO()
        await self.bot.download_file(file.file_path, destination=buffer)
        return web.Response(body=buffer.getvalue(), content_type='image/jpeg')

    async def candidate(self, req):
        p = await self.store.profile(req['user']['id'])
        if not p:
            raise ApiError(409, 'Сначала создайте анкету')
        return web.json_response({'profile': public_profile(await self.store.candidate(p['id'])), 'active': bool(p['active'])})

    async def reaction(self, req):
        data = await req.json()
        target, kind = number(data.get('target')), data.get('kind')
        if kind not in {'like', 'skip'}:
            raise ApiError(400, 'Неизвестная реакция')
        async with self.writes:
            candidate = await self.store.candidate(req['user']['id'])
            if not candidate or candidate['id'] != target:
                raise ApiError(409, 'Анкета уже просмотрена или недоступна')
            result = await self.store.react(req['user']['id'], target, kind, notify=True)
        if result:
            self.publish(req['user']['id'], target)
        return web.json_response({'match': result is True})

    async def matches(self, req):
        uid = req['user']['id']
        offset = number(req.query.get('offset', 0), 0, 1000000)
        rows = await self.store.matches(uid, offset)
        output = []
        for p in rows:
            summary = await self.store.chat_summary(uid, p['id'])
            output.append({**public_profile(p), **summary})
        return web.json_response({'matches': output, 'more': len(rows) == 5, 'unread_total': await self.store.unread_total(uid)})

    async def messages(self, req):
        uid, target = req['user']['id'], number(req.match_info['target'])
        if req.method == 'POST':
            data = await req.json()
            body, nonce = data.get('body', ''), data.get('nonce', '')
            if not isinstance(body, str) or not 1 <= len(body.strip()) <= 2000:
                raise ApiError(400, 'Сообщение: от 1 до 2000 символов')
            if not isinstance(nonce, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', nonce):
                raise ApiError(400, 'Неверный идентификатор сообщения')
            row = await self.store.web_send(uid, target, body.strip(), nonce)
            if row is None:
                raise ApiError(409, 'Диалог недоступен')
            self.publish(uid, target)
            return web.json_response({'message': row})
        after = number(req.query['after'], 0, 2**63-1) if 'after' in req.query else None
        before = number(req.query['before'], 1, 2**63-1) if 'before' in req.query else None
        rows = await self.store.web_messages(uid, target, before, after)
        if rows is None:
            raise ApiError(409, 'Диалог недоступен')
        return web.json_response({'messages': rows, 'summary': await self.store.chat_summary(uid, target)})

    async def read(self, req):
        data = await req.json()
        okay = await self.store.read_messages(req['user']['id'], number(req.match_info['target']), number(data.get('last_id'), 0, 2**63-1))
        if okay is None:
            raise ApiError(409, 'Диалог недоступен')
        if okay:
            self.publish(number(req.match_info['target']))
        return web.json_response({'ok': True})

    async def settings(self, req):
        uid, data = req['user']['id'], await req.json()
        if not await self.store.profile(uid):
            raise ApiError(404, 'Анкета не найдена')
        if 'active' in data:
            if not isinstance(data['active'], bool):
                raise ApiError(400, 'Неверное значение видимости')
            await self.store.active(uid, data['active'])
        if 'min_age' in data or 'max_age' in data:
            low, high = number(data.get('min_age'), 18, 99), number(data.get('max_age'), 18, 99)
            if low > high:
                raise ApiError(400, 'Возраст «от» должен быть меньше возраста «до»')
            await self.store.filters(uid, low, high)
        return web.json_response({'ok': True})

    async def action(self, req):
        uid, action = req['user']['id'], req.match_info['action']
        if action == 'reset':
            await self.store.reset_skips(uid)
        else:
            data = await req.json()
            target = number(data.get('target'))
            if uid == target or not await self.visible(uid, target):
                raise ApiError(404, 'Анкета недоступна')
            if action == 'unmatch':
                await self.store.unmatch(uid, target)
            elif action in {'block', 'report'}:
                reason = data.get('reason') if action == 'report' else None
                if action == 'report' and reason not in {'spam', 'content', 'underage'}:
                    raise ApiError(400, 'Выберите причину жалобы')
                await self.store.block(uid, target, reason)
                if reason and self.admin_id:
                    try:
                        await self.bot.send_message(self.admin_id, 'Новая жалоба в Мэтч. Откройте /admin для проверки.')
                    except TelegramAPIError:
                        pass
            else:
                raise ApiError(404, 'Неизвестное действие')
        if action != 'reset':
            self.publish(uid, target)
        return web.json_response({'ok': True})


def create_app(store, bot, token, admin_id=None, bootstrap=False, public_url=None):
    service = Service(store, bot, token, admin_id, bootstrap, public_url)
    app = web.Application(middlewares=[boundary], client_max_size=6 * 1024 * 1024)
    app[API] = service
    register_admin(app, service, ApiError, number, public_profile)
    app.router.add_get('/api/deploy/challenge',service.deployment_challenge)
    app.router.add_post('/api/deploy/import',service.import_database)
    app.router.add_get('/api/events', service.events)
    app.router.add_get('/api/me', service.me)
    app.router.add_delete('/api/me', service.me)
    app.router.add_post('/api/profile', service.profile)
    app.router.add_get('/api/photos/{target}', service.photo)
    app.router.add_get('/api/profiles/{target}', service.get_profile)
    app.router.add_get('/api/candidate', service.candidate)
    app.router.add_post('/api/reactions', service.reaction)
    app.router.add_get('/api/matches', service.matches)
    app.router.add_get('/api/chats/{target}/messages', service.messages)
    app.router.add_post('/api/chats/{target}/messages', service.messages)
    app.router.add_post('/api/chats/{target}/read', service.read)
    app.router.add_post('/api/settings', service.settings)
    app.router.add_post('/api/actions/{action}', service.action)
    async def health(request):
        return web.json_response({'ok': True,'awaiting_import':service.bootstrap_pending})
    async def index(request):
        return web.FileResponse(ROOT / 'index.html')
    app.router.add_get('/health', health)
    app.router.add_get('/', index)
    app.router.add_static('/assets/', ROOT)
    return app


if __name__ == '__main__':
    import argparse
    import secrets
    from dating.store import Store
    parser = argparse.ArgumentParser(description='Local Mini App design preview: no real Telegram API access')
    parser.add_argument('--port', type=int, default=8081)
    args = parser.parse_args()
    async def preview():
        store = await Store(':memory:').open()
        app = create_app(store, None, secrets.token_urlsafe(32))
        async def cleanup(app):
            await store.close()
        app.on_cleanup.append(cleanup)
        return app
    web.run_app(preview(), host='127.0.0.1', port=args.port, access_log=None)
