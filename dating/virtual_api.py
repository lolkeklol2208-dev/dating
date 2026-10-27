"""Participant consent and an operator inbox restricted to fictional characters."""
import re
from aiohttp import web

from dating.virtual_store import CONSENT_VERSION, NOTICE


def register_virtual(app, service, error, number):
    def operator(req):
        active=req.path.startswith('/api/admin/')
        if active and (not service.admin_id or req['user']['id']!=service.admin_id):
            raise error(403,'Тестовые диалоги доступны только администратору')
        return active

    async def session(req):
        uid=req['user']['id']
        if req.method=='POST':
            data=await req.json()
            if not isinstance(data,dict) or type(data.get('enabled')) is not bool:
                raise error(400,'Выберите режим тестовых знакомств')
            if data['enabled']:
                if not service.admin_id:
                    raise error(503,'Администратор для тестовых диалогов не настроен')
                if data.get('accepted') is not True or type(data.get('version')) is not int or data['version']!=CONSENT_VERSION:
                    raise error(400,'Подтвердите, что анкеты вымышлены и отвечает администратор')
            await service.store.virtual_consent(uid,str(req['user'].get('first_name') or 'Участник'),data['enabled'])
            service.publish(uid,service.admin_id)
        return web.json_response(await service.store.virtual_state(uid))

    async def reaction(req):
        uid=req['user']['id']
        data=await req.json()
        if not isinstance(data,dict) or data.get('kind') not in {'like','skip'} or not isinstance(data.get('target'),str):
            raise error(400,'Проверьте реакцию')
        async with service.writes:
            candidate=await service.feed_candidate(uid)
            if not candidate or not candidate.get('is_virtual') or candidate['character_id']!=data['target']:
                raise error(409,'Тестовая анкета уже просмотрена или режим выключен')
            tid=await service.store.virtual_react(uid,data['target'],data['kind'])
            if tid is None:
                raise error(409,'Для тестовых мэтчей нужно согласие участника')
        service.publish(uid,service.admin_id)
        return web.json_response({'match':bool(tid),'thread_id':tid or None,'is_virtual':True})

    async def threads(req):
        is_operator=operator(req)
        offset=number(req.query.get('offset',0),0,1000000)
        result=await service.store.virtual_threads(req['user']['id'],is_operator,offset)
        return web.json_response({**result,'notice':NOTICE})

    async def messages(req):
        is_operator=operator(req)
        uid,tid=req['user']['id'],number(req.match_info['thread_id'])
        if req.method=='POST':
            data=await req.json()
            if not isinstance(data,dict):
                raise error(400,'Ожидался текст сообщения')
            body,nonce=data.get('body'),data.get('nonce')
            if not isinstance(body,str) or not 1<=len(body.strip())<=2000:
                raise error(400,'Сообщение: от 1 до 2000 символов')
            if not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',nonce):
                raise error(400,'Неверный идентификатор сообщения')
            result=await service.store.virtual_send(uid,tid,body.strip(),nonce,is_operator)
            if not result:
                raise error(409,'Тестовый диалог недоступен или согласие отозвано')
            service.publish(result['participant_id'],service.admin_id)
            return web.json_response({'message':result['message']})
        after=number(req.query['after'],0,2**63-1) if 'after' in req.query else None
        before=number(req.query['before'],1,2**63-1) if 'before' in req.query else None
        if after is not None and before is not None:
            raise error(400,'Используйте один указатель истории')
        result=await service.store.virtual_messages(uid,tid,is_operator,before,after)
        if not result:
            raise error(409,'Тестовый диалог недоступен или согласие отозвано')
        return web.json_response(result)

    async def read(req):
        is_operator=operator(req)
        data=await req.json()
        if not isinstance(data,dict):
            raise error(400,'Укажите последнее прочитанное сообщение')
        result=await service.store.virtual_read(req['user']['id'],number(req.match_info['thread_id']),number(data.get('last_id'),0,2**63-1),is_operator)
        if result is None:
            raise error(409,'Тестовый диалог закрыт')
        if result is False:
            raise error(400,'Сообщение не относится к этому диалогу')
        service.publish(result,service.admin_id)
        return web.json_response({'ok':True})

    async def close(req):
        if not await service.store.virtual_close(req['user']['id'],number(req.match_info['thread_id'])):
            raise error(409,'Тестовый диалог уже закрыт')
        service.publish(req['user']['id'],service.admin_id)
        return web.json_response({'ok':True})

    app.router.add_get('/api/virtual/session',session)
    app.router.add_post('/api/virtual/session',session)
    app.router.add_post('/api/virtual/reactions',reaction)
    for base in ('/api/virtual/threads','/api/admin/virtual/threads'):
        app.router.add_get(base,threads)
        app.router.add_get(base+'/{thread_id}/messages',messages)
        app.router.add_post(base+'/{thread_id}/messages',messages)
        app.router.add_post(base+'/{thread_id}/read',read)
    app.router.add_delete('/api/virtual/threads/{thread_id}',close)
