"""Initialize only the app's dedicated persistent directory, then drop root."""
import os
from pathlib import Path
import stat
import sys

DATA_ROOT = Path('/data/metch')
APP_UID = 10001
APP_GID = 10001


def initialize_directory(root=DATA_ROOT, uid=APP_UID, gid=APP_GID):
    if root.is_symlink():
        raise RuntimeError('Каталог данных не должен быть ссылкой')
    root.mkdir(parents=True,exist_ok=True)
    if not root.is_dir():
        raise RuntimeError('Нужен каталог постоянных данных')
    # Never take ownership of another user's unrelated data or follow links.
    entries=[root]
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            entries.append(Path(parent)/name)
    for entry in entries:
        metadata=entry.lstat()
        if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid not in (0,uid):
            raise RuntimeError('Каталог содержит ссылки или файлы другого пользователя')
        if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            raise RuntimeError('Неожиданный тип файла в каталоге данных')
    for entry in entries:
        os.chown(entry,uid,gid)
    root.chmod(0o700)


def main():
    if os.geteuid()==0:
        initialize_directory()
        os.setgroups([])
        os.setgid(APP_GID)
        os.setuid(APP_UID)
    if not DATA_ROOT.is_dir() or not os.access(DATA_ROOT,os.W_OK):
        raise SystemExit('Постоянное хранилище /data/metch недоступно для записи')
    # Python/application never starts with root privileges.
    os.execv(sys.executable,[sys.executable,'-m','dating'])


if __name__=='__main__':
    main()
