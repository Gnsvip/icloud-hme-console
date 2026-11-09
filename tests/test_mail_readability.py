"""Synthetic long-message and legacy-cache checks; no real IMAP connections."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

import mail_cache
from icloud_mail import ICloudMail, MAX_BODY_CHARS


@pytest.mark.parametrize('content_type', ['text/plain', 'text/html'])
def test_long_tracking_links_do_not_cut_off_the_message_tail(content_type):
    link = 'https://tracking.example.test/click?token=' + 'x' * 1700
    text = '邮件开头\n' + '\n'.join(f'链接 ({link})' for _ in range(7)) + '\n这是邮件末尾，正文完整。'
    if content_type == 'text/html':
        text = '<html><body><p>' + text.replace('\n', '</p><p>') + '</p></body></html>'
    raw = f'Content-Type: {content_type}; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n{text}'.encode()
    client = ICloudMail('synthetic@example.test', 'synthetic-password')
    client._conn = Mock()
    client._conn.uid.return_value = ('OK', [(b'1 (BODY[] {12000}', raw), b')'])
    result = client._fetch_full_message(b'1')
    assert result['body'].endswith('这是邮件末尾，正文完整。')
    assert result['body_truncated'] is False and len(result['body']) > 5000
    client._conn.uid.assert_called_once_with('FETCH', b'1', '(BODY.PEEK[])')


def test_oversized_body_remains_bounded_and_reports_truncation():
    raw = b'Content-Type: text/plain; charset=utf-8\r\n\r\n' + b'x' * (MAX_BODY_CHARS + 10)
    client = ICloudMail('synthetic@example.test', 'synthetic-password')
    client._conn = Mock()
    client._conn.uid.return_value = ('OK', [(b'1 (BODY[]', raw)])
    result = client._fetch_full_message(b'1')
    assert len(result['body']) == MAX_BODY_CHARS and result['body_truncated'] is True


def test_legacy_truncated_body_is_refetched_without_removing_cached_mail(tmp_path, monkeypatch):
    path = tmp_path / 'cache.json'
    monkeypatch.setattr(mail_cache, 'CACHE_FILE', path)
    cache = mail_cache.MailCache()
    old = {'id': '1', 'subject': '保留标题', 'body': 'x' * 5000}
    cache.set_message('account', '1', old)
    cache.set_inbox('account', [old])
    cache.set_alias_mail('account', 'alias@example.test', [old])
    original = path.read_bytes()
    assert cache.get_message('account', '1') is None
    for row in [cache.get_inbox('account')[0], cache.get_alias_mail('account', 'alias@example.test')[0],
                cache.get_all_alias_mail('account')['alias@example.test'][0]]:
        assert row['subject'] == '保留标题' and not row.get('body') and not row['has_body']
    assert path.read_bytes() == original
    assert json.loads(path.read_text(encoding='utf-8'))['account']['message_bodies']['1']['body'] == old['body']
    new = {**old, 'body_truncated': False}
    cache.set_message('account', '1', new)
    assert cache.get_message('account', '1') == new


def test_opening_legacy_body_fetches_once_then_reuses_corrected_cache(tmp_path, monkeypatch):
    from services import mail_service
    monkeypatch.setattr(mail_cache, 'CACHE_FILE', tmp_path / 'cache.json')
    cache = mail_cache.MailCache()
    cache.set_message('account', '1', {'id': '1', 'body': 'x' * 5000})
    client = Mock()
    new = {'id': '1', 'body': '完整的邮件正文', 'body_truncated': False}
    client.fetch_full.return_value = new
    manager = SimpleNamespace(_cache=cache, get_mail_client=Mock(return_value=client))
    monkeypatch.setattr(mail_service, '_account_mgr', manager)
    monkeypatch.setattr(mail_service, '_run_imap_with_timeout', lambda load, **kwargs: load())
    monkeypatch.setattr(mail_service, '_sync_inventory_from_messages', Mock())
    with Flask(__name__).test_request_context():
        assert mail_service.api_message_body('account', '1').json['message'] == new
        assert mail_service.api_message_body('account', '1').json['cached'] is True
    client.fetch_full.assert_called_once_with(b'1')
    client.disconnect.assert_called_once()
