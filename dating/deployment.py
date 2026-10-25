"""Authenticated, one-time database bootstrap for a fresh deployment."""
from contextlib import closing
import hashlib
import hmac
from pathlib import Path
import sqlite3
import time

MAX_SNAPSHOT = 64 * 1024 * 1024


class BootstrapError(Exception):
    pass


def import_signature(token, timestamp, digest):
    key=hmac.new(token.encode(),b'metch-database-bootstrap-v1',hashlib.sha256).digest()
    return hmac.new(key,f'{timestamp}\n{digest}'.encode(),hashlib.sha256).hexdigest()


def verify_import_headers(token, timestamp, digest, signature, now=None):
    try:
        stamp=int(timestamp)
    except (ValueError,TypeError):
        return False
    now=time.time() if now is None else now
    if stamp<now-300 or stamp>now+30 or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        return False
    return hmac.compare_digest(import_signature(token,str(stamp),digest),signature)


def validate_snapshot(path):
    path=Path(path)
    if not 100 <= path.stat().st_size <= MAX_SNAPSHOT:
        raise BootstrapError('Неверный размер базы')
    with path.open('rb') as file:
        if file.read(16)!=b'SQLite format 3\x00':
            raise BootstrapError('Нужна SQLite-резервная копия')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise BootstrapError('База не прошла проверку целостности')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise BootstrapError('Нарушены связи базы')
            # Check selected source columns before replacing the empty destination.
            db.execute('SELECT id,name,age,gender,seeking,city,bio,photo,active,min_age,max_age FROM profiles LIMIT 1')
            db.execute('SELECT a,b,sender,body,status FROM messages LIMIT 1')
            for table in ('profiles','reactions','matches','blocks','reports','bans','fsm','conversations'):
                db.execute(f'SELECT count(*) FROM {table}').fetchone()
    except sqlite3.Error:
        raise BootstrapError('Неподдерживаемая или повреждённая база') from None


def service_proof(token, public_url, nonce):
    key=hmac.new(token.encode(),b'metch-database-bootstrap-v1',hashlib.sha256).digest()
    return hmac.new(key,f'service-proof\n{public_url}\n{nonce}'.encode(),hashlib.sha256).hexdigest()
