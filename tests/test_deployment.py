import hashlib
import time
from unittest.mock import AsyncMock
from types import SimpleNamespace

from aiohttp.test_utils import TestClient,TestServer
import pytest

from dating.backup import backup
from dating.deployment import BootstrapError,import_signature,service_proof,verify_import_headers
from dating.store import Store
from dating.webserver import create_app,API
from tests.test_store import add

TOKEN='offline-bootstrap-key'


def signed(body):
    stamp=str(int(time.time()))
    digest=hashlib.sha256(body).hexdigest()
    return {'X-Metch-Time':stamp,'X-Metch-SHA256':digest,'X-Metch-Signature':import_signature(TOKEN,stamp,digest)}


def test_import_auth_expiry_checksum_and_domain_binding():
    body=b'test';headers=signed(body)
    assert verify_import_headers(TOKEN,headers['X-Metch-Time'],headers['X-Metch-SHA256'],headers['X-Metch-Signature'])
    assert not verify_import_headers(TOKEN,headers['X-Metch-Time'],headers['X-Metch-SHA256'],'wrong')
    assert not verify_import_headers(TOKEN,headers['X-Metch-Time'],headers['X-Metch-SHA256'],headers['X-Metch-Signature'],now=time.time()+3600)
    assert service_proof(TOKEN,'https://one.example','a'*64)!=service_proof(TOKEN,'https://two.example','a'*64)


async def test_full_bootstrap_preserves_users_history_drafts_and_closes_import(tmp_path):
    old=await Store(str(tmp_path/'source.sqlite3')).open()
    await add(old,7,name='Existing user')
    await add(old,8)
    await old.react(7,8,'like')
    await old.react(8,7,'like')
    await old.web_send(7,8,'Keep this history','bootstrap-nonce-0001')
    async with old.transaction():
        await old.db.execute("INSERT INTO fsm VALUES ('draft',7,'Form:age','{}')")
    snapshot=tmp_path/'copy.sqlite3'
    backup(old.path,str(snapshot))
    body=snapshot.read_bytes()
    new=await Store(str(tmp_path/'target.sqlite3')).open()
    client=TestClient(TestServer(create_app(new,SimpleNamespace(send_message=AsyncMock()),TOKEN,99,True,'https://actual-test.onrender.com')))
    await client.start_server()
    try:
        assert (await (await client.get('/health')).json())['awaiting_import']
        assert (await client.get('/api/me')).status==503
        assert (await client.post('/api/deploy/import',data=body)).status==403
        assert (await new.stats())['profiles']==0
        challenge=await (await client.get('/api/deploy/challenge?nonce='+'a'*64)).json()
        assert challenge['proof']==service_proof(TOKEN,challenge['url'],'a'*64)
        bad=await client.post('/api/deploy/import',data=body+b'changed',headers=signed(body))
        assert bad.status==400
        result=await client.post('/api/deploy/import',data=body,headers=signed(body))
        assert result.status==200
        assert (await result.json())['stats']['profiles']==2
        assert client.app[API].ready.is_set()
        assert (await new.profile(7))['name']=='Existing user'
        assert (await new.web_messages(8,7))[0]['body']=='Keep this history'
        async with new.db.execute('SELECT state FROM fsm WHERE user_id=7') as cursor:
            assert (await cursor.fetchone())[0]=='Form:age'
        assert not await new.needs_bootstrap()
        assert (await client.post('/api/deploy/import',data=body,headers=signed(body))).status==404
        assert (await client.get('/api/me')).status==401
        assert not (await (await client.get('/health')).json())['awaiting_import']
        assert not list(tmp_path.glob('.import-*'))
        assert (await old.profile(7))['name']=='Existing user'
    finally:
        await client.close()
        await old.close()
        await new.close()


async def test_populated_destination_is_never_replaced(tmp_path):
    source=await Store(str(tmp_path/'source.sqlite3')).open()
    await add(source,1)
    snapshot=tmp_path/'snapshot.sqlite3'
    backup(source.path,str(snapshot))
    target=await Store(str(tmp_path/'target.sqlite3')).open()
    try:
        await add(target,2,name='Preserve target')
        assert not await target.needs_bootstrap()
        with pytest.raises(BootstrapError):
            await target.import_snapshot(snapshot)
        assert (await target.profile(2))['name']=='Preserve target'
        assert await target.profile(1) is None
    finally:
        await source.close()
        await target.close()


async def test_operator_transfer_over_verified_https(tmp_path,monkeypatch):
    import shutil
    import ssl
    import subprocess
    from dating.deploy_transfer import transfer
    if not shutil.which('openssl'):
        pytest.skip('OpenSSL needed to create a temporary test CA')
    key=tmp_path/'key.pem';cert=tmp_path/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
                    '-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert,key)
    monkeypatch.setenv('SSL_CERT_FILE',str(cert))
    monkeypatch.setenv('NO_PROXY','127.0.0.1,localhost')
    source=await Store(str(tmp_path/'live.sqlite3')).open()
    await add(source,7)
    await add(source,8)
    await source.react(7,8,'like')
    await source.react(8,7,'like')
    await source.web_send(8,7,'HTTPS full transfer','https-transfer-nonce0001')
    target=await Store(str(tmp_path/'new.sqlite3')).open()
    app=create_app(target,SimpleNamespace(send_message=AsyncMock()),TOKEN,99,True,'https://temporary.invalid')
    server=TestServer(app,scheme='https')
    await server.start_server(ssl=context)
    url=str(server.make_url('/')).rstrip('/')
    app[API].public_url=url
    try:
        with pytest.raises(BootstrapError):
            await transfer(url,source.path,'wrong-token')
        assert (await target.stats())['profiles']==0
        result=await transfer(url,source.path,TOKEN)
        assert result['profiles']==2 and result['messages']==1
        assert (await target.web_messages(7,8))[0]['body']=='HTTPS full transfer'
        assert (await source.profile(7))['id']==7
        with pytest.raises(BootstrapError):
            await transfer(url,source.path,TOKEN)
        assert list((tmp_path/'backups').glob('pre-deployment-*.sqlite3'))
    finally:
        await server.close()
        await source.close()
        await target.close()


async def test_failed_activation_restores_empty_destination(tmp_path):
    import sqlite3
    source=await Store(str(tmp_path/'source.sqlite3')).open()
    await add(source,7)
    stage=tmp_path/'stage.sqlite3'
    backup(source.path,str(stage))
    db=sqlite3.connect(stage)
    try:
        db.execute('DROP TABLE deployment_state')
        db.execute('CREATE TABLE deployment_state (invalid TEXT)')
        db.commit()
    finally:
        db.close()
    target=await Store(str(tmp_path/'target.sqlite3')).open()
    try:
        with pytest.raises(sqlite3.Error):
            await target.import_snapshot(stage)
        assert (await target.stats())['profiles']==0
        assert await target.needs_bootstrap()
        assert (await source.profile(7))['id']==7
    finally:
        await source.close()
        await target.close()
