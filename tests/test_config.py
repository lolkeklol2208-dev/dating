import pytest
from dating.config import web_settings


def test_local_defaults_do_not_enable_or_publish_app():
    s=web_settings({})
    assert (s.url,s.host,s.port,s.enabled)==(None,'127.0.0.1',8080,False)


def test_render_automatically_uses_assigned_https_url_and_port():
    s=web_settings({'RENDER_EXTERNAL_URL':'https://assigned-test.onrender.com/','PORT':'10000'})
    assert s.url=='https://assigned-test.onrender.com' and s.enabled
    assert s.host=='0.0.0.0' and s.port==10000


def test_explicit_settings_override_platform_defaults():
    s=web_settings({'RENDER_EXTERNAL_URL':'https://assigned-test.onrender.com', 'WEBAPP_URL':'https://custom.example',
                    'PORT':'10000','WEB_PORT':'8088','WEB_HOST':'127.0.0.1'})
    assert (s.url,s.host,s.port)==('https://custom.example','127.0.0.1',8088)


@pytest.mark.parametrize('url',['http://example.com','https://user:pass@example.com','https://example.com/app',
                                'https://example.com/?query=1','https://example.com/#fragment','https://example.com:bad'])
def test_invalid_app_urls_are_rejected(url):
    with pytest.raises(ValueError):
        web_settings({'WEBAPP_URL':url})


@pytest.mark.parametrize('port',['0','65536','-1','port','１２３'])
def test_invalid_ports_fail_before_opening_socket(port):
    with pytest.raises(ValueError):
        web_settings({'PORT':port})
