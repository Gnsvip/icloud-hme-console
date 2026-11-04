"""Checks for the redesigned console and write reduction. Uses synthetic data only."""
import concurrent.futures
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mail_cache
from inventory_manager import InventoryManager


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(mail_cache, 'CACHE_FILE', tmp_path / 'mail.json')
    return mail_cache.MailCache()


def test_batch_persists_once_and_noop_does_not_write(cache):
    messages = {str(i): {'id': str(i), 'body': f'message {i}'} for i in range(30)}
    with patch.object(cache, '_save', wraps=cache._save) as save:
        cache.set_messages('one', messages)
        assert save.call_count == 1
        cache.set_messages('one', messages)
        assert save.call_count == 1
    assert mail_cache.MailCache().get_message('one', '29')['body'] == 'message 29'


def test_cache_atomic_failure_preserves_disk_and_retries(cache):
    cache.set_message('one', '1', {'body': 'previous'})
    before = mail_cache.CACHE_FILE.read_bytes()
    with patch.object(mail_cache.os, 'replace', side_effect=OSError('simulated disk failure')):
        with pytest.raises(OSError):
            cache.set_messages('one', {'2': {'body': 'new'}})
    assert mail_cache.CACHE_FILE.read_bytes() == before
    assert not list(mail_cache.CACHE_FILE.parent.glob('.mail-cache-*'))
    cache.set_messages('one', {'2': {'body': 'new'}})
    reloaded = mail_cache.MailCache()
    assert reloaded.get_message('one', '1')['body'] == 'previous'
    assert reloaded.get_message('one', '2')['body'] == 'new'


def test_concurrent_cache_batches_preserve_all_accounts(cache):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: cache.set_messages(str(i % 3), {str(i): {'body': str(i)}}), range(30)))
    reloaded = mail_cache.MailCache()
    for i in range(30):
        assert reloaded.get_message(str(i % 3), str(i))['body'] == str(i)


def test_identical_alias_cache_does_not_write(cache):
    batch = {'a@icloud.com': [{'id': '1', 'body': 'sample'}]}
    with patch.object(cache, '_save', wraps=cache._save) as save:
        cache.set_alias_mail_batch('one', batch)
        cache.set_alias_mail_batch('one', batch)
        cache.set_alias_mail('one', 'a@icloud.com', batch['a@icloud.com'])
        assert save.call_count == 1


def test_inventory_noop_preserves_timestamp_and_changes_are_saved(tmp_path):
    inventory = InventoryManager(tmp_path / 'inventory.json')
    rows = [{'email': 'test@icloud.com', 'label': 'initial', 'account_id': 'one'}]
    inventory.sync_aliases(rows)
    before = inventory.path.read_bytes()
    with patch.object(inventory, 'save', wraps=inventory.save) as save:
        assert inventory.sync_aliases(rows)['changed'] == 0
        save.assert_not_called()
        assert inventory.path.read_bytes() == before
        assert inventory.sync_aliases([{**rows[0], 'label': 'changed', 'account_id': 'two'}])['changed'] == 1
        assert save.call_count == 1
    item = inventory.load()['items']['test@icloud.com']
    assert item['label'] == 'changed' and item['account_id'] == 'two'


@pytest.fixture
def inventory_api(tmp_path, monkeypatch):
    from services import code_inventory_service as service
    inv = InventoryManager(tmp_path / 'inventory.json')
    inv.sync_aliases([{'email': f'box{i:04}@icloud.com', 'account_id': 'one', 'label': 'sample'} for i in range(153)])
    inv.sync_aliases([{'email': 'private@icloud.com', 'account_id': 'inactive'}])
    monkeypatch.setattr(service, '_inventory', inv)
    monkeypatch.setattr(service, '_active_account_ids', lambda: {'one'})
    monkeypatch.setattr(service, '_read_alias_cache', lambda: {'aliases': []})
    monkeypatch.setattr(service, '_sync_inventory_from_known', lambda *_: None)
    monkeypatch.setattr(service, '_sync_inventory_from_mail_cache', lambda: None)
    app = Flask(__name__)
    app.add_url_rule('/api/inventory', view_func=service.api_inventory)
    return app.test_client(), service


def test_inventory_pagination_filters_totals_and_legacy_compatibility(inventory_api):
    client, service = inventory_api
    with patch.object(service, '_attach_status_model', side_effect=lambda rows: rows) as enrich:
        first = client.get('/api/inventory?page=1&page_size=20').get_json()
        assert first['count'] == 153 and first['pages'] == 8 and len(first['items']) == 20
        assert first['summary']['all'] == 153
        assert len(enrich.call_args.args[0]) == 20
        last = client.get('/api/inventory?page=999&page_size=20').get_json()
        assert last['page'] == 8 and len(last['items']) == 13
        assert not {r['email'] for r in first['items']} & {r['email'] for r in last['items']}
        assert len(client.get('/api/inventory').get_json()['items']) == 153
        filtered = client.get('/api/inventory?q=box0001&page_size=20').get_json()
        assert filtered['count'] == 1 and filtered['items'][0]['email'] == 'box0001@icloud.com'
        assert client.get('/api/inventory?account_id=inactive').get_json()['count'] == 0
        assert client.get('/api/inventory?page=x&page_size=x').get_json()['ok']
        assert len(client.get('/api/inventory?page=1&page_size=-10').get_json()['items']) == 1


def test_body_fetch_batches_and_disconnects_when_save_fails(cache, monkeypatch):
    import app_core as core
    mail = Mock()
    mail.fetch_full.side_effect = lambda uid: {'id': uid.decode(), 'body': 'sample'}
    monkeypatch.setattr(core, '_account_mgr', SimpleNamespace(_cache=cache, get_mail_client=lambda _: mail))
    with patch.object(cache, 'set_messages', wraps=cache.set_messages) as save:
        result = core._fetch_missing_bodies('one', [{'id': '1'}, {'id': '2'}])
        assert len(result) == 2 and all(m['body'] == 'sample' for m in result)
        assert save.call_count == 1
    mail.disconnect.assert_called_once()
    mail.disconnect.reset_mock()
    with patch.object(cache, 'set_messages', side_effect=OSError('disk failure')):
        with pytest.raises(OSError):
            core._fetch_missing_bodies('one', [{'id': '3'}])
    mail.disconnect.assert_called_once()


def test_react_shell_auth_and_cache_headers():
    import app_core as core
    from web_ui import app
    client = app.test_client()
    for path in ('/', '/admin/', '/index.html'):
        result = client.get(path)
        assert result.status_code == 200 and b'/static/admin-v2/assets/' in result.data
        assert 'no-store' in result.headers['Cache-Control']
    for path in ('/api/accounts', '/api/inventory', '/api/inbox'):
        assert client.get(path).status_code == 401
    assert client.get('/api/admin/session').get_json()['ok'] is False
    asset = next((core.HERE / 'static/admin-v2/assets').glob('*.js'))
    assert 'immutable' in client.get('/static/admin-v2/assets/' + asset.name).headers['Cache-Control']
    assert 'immutable' not in client.get('/static/admin-v2/assets/missing.js').headers['Cache-Control']
    with app.app_context():
        client.set_cookie(core.ADMIN_SESSION_COOKIE, core._admin_token())
    assert client.get('/api/admin/session').get_json()['ok'] is True
    assert client.get('/api/accounts').status_code == 200
    assert 'no-store' in client.get('/api/accounts').headers['Cache-Control']
    assert client.post('/api/admin/logout').status_code == 200
    assert client.get('/api/accounts').status_code == 401
