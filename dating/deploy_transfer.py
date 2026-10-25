"""Operator-only transfer to a fresh, authenticated deployment. No token in arguments."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import ssl
import time

import aiohttp

from dating.backup import backup
from dating.config import web_settings
from dating.deployment import BootstrapError, import_signature, service_proof, validate_snapshot


async def transfer(url, source, token):
    url=web_settings({'WEBAPP_URL':url}).url
    source=Path(source).resolve()
    folder=source.parent/'backups'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    snapshot=folder/f'pre-deployment-{stamp}.sqlite3'
    backup(str(source),str(snapshot))
    validate_snapshot(snapshot)
    with snapshot.open('rb') as file:
        digest=hashlib.file_digest(file,'sha256').hexdigest()
    connector=aiohttp.TCPConnector(ssl=ssl.create_default_context())
    async with aiohttp.ClientSession(connector=connector,trust_env=True,timeout=aiohttp.ClientTimeout(total=180)) as client:
        nonce=secrets.token_hex(32)
        async with client.get(url+'/api/deploy/challenge',params={'nonce':nonce},allow_redirects=False) as response:
            if response.status!=200:
                raise BootstrapError('Сервис ещё не ожидает импорт или импорт уже закрыт')
            proof=await response.json()
            if proof.get('url')!=url or not hmac.compare_digest(proof.get('proof',''),service_proof(token,url,nonce)):
                raise BootstrapError('Сервис не подтвердил адрес и владение тем же токеном. База не отправлена.')
        timestamp=str(int(time.time()))
        headers={'X-Metch-Time':timestamp,'X-Metch-SHA256':digest,
                 'X-Metch-Signature':import_signature(token,timestamp,digest)}
        with snapshot.open('rb') as file:
            async with client.post(url+'/api/deploy/import',data=file,headers=headers,allow_redirects=False) as response:
                if response.status!=200:
                    raise BootstrapError('Импорт не подтверждён. Локальная база и резервная копия сохранены.')
                result=await response.json()
                if not result.get('ok'):
                    raise BootstrapError('Новый сервер не подтвердил импорт')
                return result['stats']


def main():
    parser=argparse.ArgumentParser(description='Перенос базы Мэтч на новый сервер. Сначала остановите старый polling-процесс.')
    parser.add_argument('--url',required=True)
    parser.add_argument('--source',default='data/dating.sqlite3')
    args=parser.parse_args()
    token=os.environ.get('BOT_TOKEN','').strip()
    if not token:
        parser.exit(1,'Нужен BOT_TOKEN в защищённом окружении, не в аргументах.\n')
    try:
        stats=asyncio.run(transfer(args.url,args.source,token))
    except BootstrapError as exc:
        parser.exit(1,str(exc)+'\n')
    except Exception as exc:
        parser.exit(1,f'Перенос не завершён ({type(exc).__name__}); исходная база сохранена.\n')
    print('Полная база перенесена и проверена. Профилей:',stats['profiles'],'; сообщений:',stats['messages'])


if __name__=='__main__':
    main()
