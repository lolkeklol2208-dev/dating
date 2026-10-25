"""Non-secret web runtime configuration, including Render's injected URL/port."""
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class WebSettings:
    url: str | None
    host: str
    port: int
    enabled: bool


def web_settings(environment):
    render_url = environment.get('RENDER_EXTERNAL_URL', '').strip()
    url = (environment.get('WEBAPP_URL', '').strip() or render_url).rstrip('/')
    if url:
        parsed = urlparse(url)
        try:
            parsed.port
        except ValueError:
            raise ValueError('Некорректный порт HTTPS-адреса') from None
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Адрес Mini App должен быть HTTPS-корнем без параметров и подпути')
    port_text = environment.get('WEB_PORT', '').strip() or environment.get('PORT', '').strip() or '8080'
    if not port_text.isascii() or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ValueError('HTTP-порт должен быть числом от 1 до 65535')
    host = environment.get('WEB_HOST', '').strip() or ('0.0.0.0' if render_url else '127.0.0.1')
    return WebSettings(url or None, host, int(port_text), bool(url) or environment.get('WEB_ENABLED') == '1')
