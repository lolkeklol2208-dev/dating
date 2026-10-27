"""Authenticated, read-only fixture preview for ordinary Telegram participants."""
from aiohttp import web

from dating.testing_catalog import preview_profiles, preview_profile


def register_testing_preview(app, error, number):
    # create_app's boundary verifies Telegram auth, bans and rate limits first.
    async def profiles(req):
        query, city = req.query.get('q', '').strip(), req.query.get('city', '').strip()
        low = number(req.query.get('min_age', 20), 20, 30)
        high = number(req.query.get('max_age', 30), 20, 30)
        offset = number(req.query.get('offset', 0), 0, 1000000)
        if len(query) > 80 or len(city) > 60 or low > high:
            raise error(400, 'Проверьте фильтры тестового каталога')
        return web.json_response(preview_profiles(query, city, low, high, offset))

    async def profile(req):
        result = preview_profile(req.match_info['profile_id'])
        if not result:
            raise error(404, 'Тестовая анкета не найдена')
        return web.json_response({'profile': result})

    app.router.add_get('/api/test-profiles', profiles)
    app.router.add_get('/api/test-profiles/{profile_id}', profile)
