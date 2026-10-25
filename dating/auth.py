"""Telegram Mini App initData validation. Never trust initDataUnsafe for identity."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(raw, token, now=None):
    if not raw or len(raw) > 16384:
        raise ValueError('Откройте приложение через Telegram')
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError('Повторяющиеся поля авторизации')
    received = values.pop('hash', '')
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{key}={value}' for key, value in sorted(values.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        raise ValueError('Недействительная подпись Telegram')
    timestamp = int(values.get('auth_date', '0'))
    now = time.time() if now is None else now
    if timestamp < now - 86400 or timestamp > now + 60:
        raise ValueError('Сессия истекла. Закройте и снова откройте приложение')
    user = json.loads(values.get('user', '{}'))
    uid = user.get('id')
    if isinstance(uid, bool) or not isinstance(uid, int) or not 0 < uid < 2**53:
        raise ValueError('Неизвестный пользователь')
    return user
