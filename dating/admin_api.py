"""Admin API: every endpoint checks the signed identity against the configured owner."""
from aiohttp import web

from dating.admin_store import ModerationConflict


def register_admin(app, service, error, number, public_profile):
    def require_admin(req):
        if not service.admin_id or req['user']['id'] != service.admin_id:
            raise error(403, 'Этот раздел доступен только администратору')

    def offset(req):
        return number(req.query.get('offset', 0), 0, 1000000)

    async def overview(req):
        require_admin(req)
        return web.json_response(await service.store.admin_overview())

    async def users(req):
        require_admin(req)
        query = req.query.get('q', '').strip()
        status = req.query.get('status', 'all')
        if len(query) > 80 or status not in {'all', 'visible', 'hidden', 'banned'}:
            raise error(400, 'Проверьте поиск и фильтр пользователей')
        return web.json_response(await service.store.admin_users(query, status, offset(req)))

    async def user(req):
        require_admin(req)
        result = await service.store.admin_user(number(req.match_info['target']))
        if not result:
            raise error(404, 'Пользователь не найден')
        profile = result['profile']
        result['profile'] = {**public_profile(profile, own=True), 'username': profile['username']} if profile else None
        return web.json_response(result)

    async def reports(req):
        require_admin(req)
        status = req.query.get('status', 'open')
        if status not in {'open', 'reviewed'}:
            raise error(400, 'Выберите статус жалоб')
        return web.json_response(await service.store.admin_reports(status, offset(req)))

    async def audit(req):
        require_admin(req)
        return web.json_response(await service.store.admin_audit(offset(req)))

    async def moderate(req):
        require_admin(req)
        data = await req.json()
        if not isinstance(data, dict):
            raise error(400, 'Ожидались поля решения модератора')
        target = number(data.get('target'))
        actor = number(data['report_actor']) if 'report_actor' in data else None
        try:
            await service.store.moderate(service.admin_id, target, data.get('action'), data.get('reason'), actor)
        except ValueError as exc:
            raise error(400, str(exc))
        except ModerationConflict as exc:
            raise error(409, str(exc))
        service.publish(target)
        return web.json_response({'ok': True})

    async def test_profiles(req):
        require_admin(req)
        query, city = req.query.get('q', '').strip(), req.query.get('city', '').strip()
        status = req.query.get('status', 'all')
        low = number(req.query.get('min_age', 20), 20, 30)
        high = number(req.query.get('max_age', 30), 20, 30)
        if len(query) > 80 or len(city) > 60 or low > high or status not in {'all','new','reviewed','needs_work'}:
            raise error(400, 'Проверьте фильтры тестового каталога')
        return web.json_response(await service.store.testing_profiles(query, city, low, high, status, offset(req)))

    async def test_export(req):
        require_admin(req)
        return web.json_response(await service.store.testing_profiles(limit=100))

    async def test_profile(req):
        require_admin(req)
        profile_id = req.match_info['profile_id']
        if not await service.store.testing_profile(profile_id):
            raise error(404, 'Тестовая анкета не найдена')
        if req.method == 'POST':
            data = await req.json()
            if not isinstance(data, dict) or not isinstance(data.get('notes'), str):
                raise error(400, 'Заполните заметку')
            rating = number(data.get('rating'), 0, 5)
            revision = number(data.get('revision'), 0, 2**31-1)
            status = data.get('status')
            if status not in {'new','reviewed','needs_work'} or len(data['notes']) > 2000:
                raise error(400, 'Заметка до 2000 символов; выберите статус проверки')
            try:
                await service.store.review_testing_profile(profile_id, rating, status, data['notes'].strip(), revision)
            except ModerationConflict as exc:
                raise error(409, str(exc))
        return web.json_response({'profile': await service.store.testing_profile(profile_id)})

    app.router.add_get('/api/admin/overview', overview)
    app.router.add_get('/api/admin/users', users)
    app.router.add_get('/api/admin/users/{target}', user)
    app.router.add_get('/api/admin/reports', reports)
    app.router.add_get('/api/admin/audit', audit)
    app.router.add_post('/api/admin/moderate', moderate)
    app.router.add_get('/api/admin/test-profiles', test_profiles)
    app.router.add_get('/api/admin/test-profiles/export', test_export)
    app.router.add_get('/api/admin/test-profiles/{profile_id}', test_profile)
    app.router.add_post('/api/admin/test-profiles/{profile_id}', test_profile)
