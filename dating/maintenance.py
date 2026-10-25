import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path

from dating.backup import backup

log = logging.getLogger(__name__)


def rotate_backup(source, directory, keep=7):
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime('metch-%Y%m%dT%H%M%S%f.sqlite3')
    backup(source, str(destination / name))
    files = sorted(destination.glob('metch-*.sqlite3'), reverse=True)
    for old in files[keep:]:
        old.unlink()


async def backup_loop(source, directory):
    while True:
        try:
            await asyncio.to_thread(rotate_backup, source, directory)
            log.info('Database backup created and verified')
        except Exception as exc:
            log.error('Backup failed (%s); source database unchanged', type(exc).__name__)
        await asyncio.sleep(86400)
