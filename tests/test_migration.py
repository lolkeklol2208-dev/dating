import sqlite3
import pytest
from dating.auth import validate_init_data
from dating.migrate_profile import MigrationError, owner_auth, read_owner_profile
from dating.store import Store
from tests.test_store import add


async def test_owner_transfer_refuses_other_users_and_preserves_source(tmp_path):
    path=str(tmp_path/'source.sqlite3')
    db=await Store(path).open()
    try:
        await add(db,1,name='Owner')
        assert read_owner_profile(path,1)['name']=='Owner'
        with pytest.raises(MigrationError):read_owner_profile(path,99)
        await add(db,2)
        with pytest.raises(MigrationError):read_owner_profile(path,1)
        assert (await db.stats())['profiles']==2
    finally:
        await db.close()


async def test_owner_transfer_refuses_history_even_for_single_owner(tmp_path):
    path=str(tmp_path/'source.sqlite3')
    db=await Store(path).open()
    try:
        await add(db,1)
        await db.ban(7,'preserve moderation')
        with pytest.raises(MigrationError):read_owner_profile(path,1)
    finally:
        await db.close()


def test_migration_auth_uses_scoped_signed_data_not_raw_token():
    token='offline-migration-token'
    auth=owner_auth(token,123,'test_owner')
    assert token not in auth
    user=validate_init_data(auth,token)
    assert user['id']==123 and user['username']=='test_owner'
