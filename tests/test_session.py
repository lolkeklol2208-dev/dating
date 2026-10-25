import ssl

from dating.session import EnvironmentSession


async def test_proxy_session_lifecycle():
    transport = EnvironmentSession()
    context = transport._connector_init["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    first = await transport.create_session()
    try:
        assert first.trust_env is True
        assert await transport.create_session() is first
    finally:
        await transport.close()
    assert first.closed
    second = await transport.create_session()
    try:
        assert second is not first and second.trust_env
    finally:
        await transport.close()
