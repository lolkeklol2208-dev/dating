from pathlib import Path
import os
import pytest
from dating.container_start import initialize_directory


def test_volume_initializer_only_manages_dedicated_directory(tmp_path):
    root=tmp_path/'metch'
    root.mkdir()
    (root/'backup').mkdir()
    (root/'backup'/'db.sqlite3').write_bytes(b'test')
    outside=tmp_path/'unrelated.txt'
    outside.write_text('preserve')
    initialize_directory(root,os.getuid(),os.getgid())
    assert root.stat().st_mode&0o777==0o700
    assert outside.read_text()=='preserve'


def test_volume_initializer_refuses_symlinks_without_changing_target(tmp_path):
    outside=tmp_path/'outside'
    outside.mkdir()
    root=tmp_path/'metch'
    root.mkdir()
    (root/'link').symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeError):
        initialize_directory(root,os.getuid(),os.getgid())
    root_link=tmp_path/'root-link'
    root_link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeError):
        initialize_directory(root_link,os.getuid(),os.getgid())
