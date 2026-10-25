"""Consistent online SQLite backups. Never copy a live WAL database as a file."""
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile


def backup(source: str, destination: str):
    source_path = Path(source).resolve()
    target = Path(destination).resolve()
    if not source_path.is_file():
        raise ValueError('Исходная база не существует')
    if source_path == target or target.exists():
        raise ValueError('Выберите новый путь: существующие файлы не перезаписываются')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.backup-', dir=target.parent)
    os.close(fd)  # mkstemp creates private (0600) files.
    try:
        with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(temp) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Проверка целостности резервной копии не пройдена')
        # Link atomically without overwriting a file created in the meantime.
        os.link(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Безопасная резервная копия базы Мэтч')
    parser.add_argument('--source', default=os.environ.get('DATABASE_PATH', 'data/dating.sqlite3'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        backup(args.source, args.output)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'Резервная копия не создана: {exc}\n')
    print('Резервная копия создана; целостность проверена.')


if __name__ == '__main__':
    main()
