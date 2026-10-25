"""Transfer the owner's sole profile through the authenticated API, without publishing SQLite.

For an initial launch only. Refuses multi-user/history databases and never overwrites
an existing different remote profile. Source DB and FSM drafts are left intact.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import ssl
import time
from urllib.parse import urlencode

import aiohttp
from aiogram import Bot

from dating.config import web_settings
from dating.session import EnvironmentSession


class MigrationError(Exception):
    pass


def read_owner_profile(source, owner):
    path=Path(source).resolve()
    if not path.is_file():
        raise MigrationError('Исходная база не найдена')
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise MigrationError('Исходная база не прошла проверку')
        rows=db.execute('SELECT * FROM profiles').fetchall()
        if len(rows)!=1 or rows[0]['id']!=owner:
            raise MigrationError('Автоперенос разрешён только для единственной анкеты владельца')
        for table in ('matches','messages','blocks','bans','reports','reactions'):
            if db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:
                raise MigrationError('В базе есть история пользователей: нужен полный перенос, не перенос одной анкеты')
        return dict(rows[0])


def owner_auth(token, owner, username=None):
    data={'auth_date':str(int(time.time())), 'user':json.dumps({'id':owner,'first_name':'Owner',**({'username':username} if username else {})})}
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{key}={value}' for key,value in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


async def migrate(url, source, owner, token):
    url=web_settings({'WEBAPP_URL':url}).url
    profile=read_owner_profile(source,owner)
    fields=('name','age','gender','seeking','city','bio')
    headers={'X-Telegram-Init-Data':owner_auth(token,owner,profile.get('username'))}
    connector=aiohttp.TCPConnector(ssl=ssl.create_default_context())
    async with aiohttp.ClientSession(headers=headers,connector=connector,trust_env=True,timeout=aiohttp.ClientTimeout(total=60)) as client:
        async def request(method,path,**kwargs):
            async with client.request(method,url+path,allow_redirects=False,**kwargs) as response:
                if response.status!=200:
                    raise MigrationError('Сервис не принял запрос переноса. Проверьте адрес, токен и состояние развёртывания.')
                return await response.json()
        remote=(await request('GET','/api/me'))
        if remote['user']['id']!=owner:
            raise MigrationError('Удалённый сервис вернул другой аккаунт')
        if remote['profile']:
            if any(remote['profile'].get(field)!=profile[field] for field in fields):
                raise MigrationError('На сервере уже есть другая версия анкеты. Автоматическая перезапись отменена.')
        else:
            async with Bot(token,session=EnvironmentSession()) as bot:
                file=await bot.get_file(profile['photo'])
                if not file.file_path or (file.file_size or 0)>5*1024*1024:
                    raise MigrationError('Фото не подходит для автоматического переноса')
                photo=await bot.download_file(file.file_path)
                form=aiohttp.FormData()
                form.add_field('profile',json.dumps({field:profile[field] for field in fields}))
                form.add_field('photo',photo.getvalue(),filename='profile.jpg',content_type='image/jpeg')
                await request('POST','/api/profile',data=form)
        await request('POST','/api/settings',json={'active':bool(profile['active']),'min_age':profile['min_age'],'max_age':profile['max_age']})
        verify=(await request('GET','/api/me'))['profile']
        for field in (*fields,'active','min_age','max_age'):
            if verify.get(field)!=profile[field]:
                raise MigrationError('Данные после переноса отличаются. Исходная база сохранена.')
    return True


def main():
    parser=argparse.ArgumentParser(description='Безопасный первичный перенос единственной анкеты владельца')
    parser.add_argument('--url',required=True)
    parser.add_argument('--source',default='data/dating.sqlite3')
    parser.add_argument('--admin-id',type=int,default=int(os.environ.get('ADMIN_ID','0')))
    args=parser.parse_args()
    token=os.environ.get('BOT_TOKEN','').strip()
    if not token or not args.admin_id:
        parser.exit(1,'Задайте BOT_TOKEN и ADMIN_ID в защищённом окружении.\n')
    try:
        asyncio.run(migrate(args.url,args.source,args.admin_id,token))
    except MigrationError as exc:
        parser.exit(1,str(exc)+'\n')
    except Exception as exc:
        parser.exit(1,f'Перенос не завершён ({type(exc).__name__}). Исходная база не изменена.\n')
    print('Анкета, фото, фильтры и видимость перенесены и проверены. Исходная база сохранена.')


if __name__=='__main__':
    main()
