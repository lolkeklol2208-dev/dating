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

    app.router.add_get('/api/admin/overview', overview)
    app.router.add_get('/api/admin/users', users)
    app.router.add_get('/api/admin/users/{target}', user)
    app.router.add_get('/api/admin/reports', reports)
    app.router.add_get('/api/admin/audit', audit)
    app.router.add_post('/api/admin/moderate', moderate)
