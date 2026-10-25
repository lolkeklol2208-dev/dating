"""Use the host's HTTPS proxy and CA configuration for Telegram requests."""
import ssl

from aiohttp import ClientSession
from aiogram.client.session.aiohttp import AiohttpSession


class EnvironmentSession(AiohttpSession):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Include the operating system / SSL_CERT_FILE trust store, including
        # managed cloud proxy CAs. Hostname and certificate checks stay enabled.
        self._connector_init["ssl"] = ssl.create_default_context()

    async def create_session(self) -> ClientSession:
        # aiogram 3.28 does not expose aiohttp's trust_env option. Keep its
        # connector lifecycle, but enable standard HTTPS_PROXY / NO_PROXY support.
        if self._should_reset_connector:
            await self.close()
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=self._connector_type(**self._connector_init),
                trust_env=True,
            )
            self._should_reset_connector = False
        return self._session
