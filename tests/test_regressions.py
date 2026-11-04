#!/usr/bin/env python3
"""回归测试 — 覆盖核心流程，发现重构中的破坏性变更。"""

import sys
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def test_parse_cookie_header_string():
    """Cookie Header String 格式解析"""
    from account_manager import AccountManager
    mgr = AccountManager()
    
    raw = "X_APPLE_WEB_KB=abc123; SESSION_TOKEN=xyz789"
    cookies = mgr.parse_cookie_input(raw)
    assert len(cookies) == 2
    assert cookies["X_APPLE_WEB_KB"] == "abc123"
    assert cookies["SESSION_TOKEN"] == "xyz789"
    print("  PASS test_parse_cookie_header_string")


def test_parse_cookie_json():
    """JSON 格式 Cookie 解析"""
    from account_manager import AccountManager
    mgr = AccountManager()
    
    raw = '{"X_APPLE_WEB_KB":"abc123","SESSION_TOKEN":"xyz789"}'
    cookies = mgr.parse_cookie_input(raw)
    assert len(cookies) == 2
    assert cookies["X_APPLE_WEB_KB"] == "abc123"
    print("  PASS test_parse_cookie_json")


def test_parse_empty_input():
    """空输入应抛出 ValueError"""
    from account_manager import AccountManager
    mgr = AccountManager()
    
    try:
        mgr.parse_cookie_input("")
        assert False, "应该抛出 ValueError"
    except ValueError:
        pass
    print("  PASS test_parse_empty_input")


def test_derive_icloud_email_primary():
    """dsInfo 有 primaryEmail 时直接使用"""
    from account_manager import AccountManager
    info = {"appleId": "user@qq.com", "primaryEmail": "user@icloud.com"}
    result = AccountManager._derive_icloud_email(info)
    assert result == "user@icloud.com"
    print("  PASS test_derive_icloud_email_primary")


def test_derive_icloud_email_appleid_is_icloud():
    """appleId 本身是 @icloud.com"""
    from account_manager import AccountManager
    info = {"appleId": "user@icloud.com", "primaryEmail": ""}
    result = AccountManager._derive_icloud_email(info)
    assert result == "user@icloud.com"
    print("  PASS test_derive_icloud_email_appleid_is_icloud")


def test_derive_icloud_email_third_party():
    """appleId 是第三方邮箱时推导"""
    from account_manager import AccountManager
    info = {"appleId": "test@gmail.com", "primaryEmail": ""}
    result = AccountManager._derive_icloud_email(info)
    assert result == "test@icloud.com"
    print("  PASS test_derive_icloud_email_third_party")


def test_mail_cache_basic():
    """邮件缓存基本读写"""
    from mail_cache import MailCache
    cache = MailCache()
    
    emails = [
        {"id": "1", "from": "a@b.com", "to": "x@icloud.com", "subject": "Hello", "date": "2025-01-01T00:00:00"},
        {"id": "2", "from": "c@d.com", "to": "y@icloud.com", "subject": "World", "date": "2025-01-02T00:00:00"},
        {"id": "1", "from": "a@b.com", "to": "x@icloud.com", "subject": "Hello Duplicate", "date": "2025-01-03T00:00:00"},
    ]
    
    cache.set_inbox("test_acc", emails)
    cached = cache.get_inbox("test_acc")
    
    # 应该有 2 封（第 3 封 id 重复被去重）
    assert len(cached) == 2, f"期望 2 封，实际 {len(cached)}"
    
    # 清理
    cache.clear_account("test_acc")
    assert len(cache.get_inbox("test_acc")) == 0
    print("  PASS test_mail_cache_basic")


def test_strip_html():
    """HTML 标签剥离"""
    from icloud_mail import _strip_html
    
    html = "<html><body><p>Hello</p><br><div>World</div></body></html>"
    text = _strip_html(html)
    assert "Hello" in text
    assert "World" in text
    assert "<p>" not in text
    assert "<html>" not in text
    print("  PASS test_strip_html")


def test_strip_html_with_link():
    """HTML 链接保留文字"""
    from icloud_mail import _strip_html
    
    html = '<a href="https://example.com">Click here</a>'
    text = _strip_html(html)
    assert "Click here" in text
    assert "example.com" in text
    print("  PASS test_strip_html_with_link")


def test_icloud_hme_account_info():
    """ICloudHME 客户端有 get_account_info 方法"""
    from icloud_hme import ICloudHME
    client = ICloudHME({}, verbose=False)
    assert hasattr(client, "get_account_info")
    # 未校验前应返回 None
    assert client.get_account_info() is None
    print("  PASS test_icloud_hme_account_info")


def test_inventory_received_mail_marks_finished():
    """只要别名收到过邮件，即使没识别验证码，也应归为已使用。"""
    from inventory_manager import InventoryManager
    with tempfile.TemporaryDirectory() as d:
        mgr = InventoryManager(Path(d) / "inventory.json")
        mgr.sync_aliases([{"email": "used.alias@icloud.com", "account_id": "acc_1"}])
        mgr.apply_messages([
            {
                "to": "Hide My Email <used.alias@icloud.com>",
                "subject": "New sign-in",
                "date": "2026-07-04T10:00:00+00:00",
            }
        ], account_id="acc_1", method="test")
        rows, summary = mgr.list_items(group="all", query="used.alias@icloud.com")
        assert rows[0]["group"] == "finished"
        assert rows[0]["status_message"] == "收到邮件，未识别验证码"
        assert summary["finished"] == 1
    print("  PASS test_inventory_received_mail_marks_finished")


def test_inventory_header_rescan_keeps_code_status():
    """正文补到验证码后，后续邮件头重扫不能把状态降级。"""
    from inventory_manager import InventoryManager
    with tempfile.TemporaryDirectory() as d:
        mgr = InventoryManager(Path(d) / "inventory.json")
        mgr.sync_aliases([{"email": "code.alias@icloud.com", "account_id": "acc_1"}])
        mgr.apply_messages([
            {
                "to": "Hide My Email <code.alias@icloud.com>",
                "subject": "你的临时 ChatGPT 登录代码",
                "body": "输入此临时验证码以继续：969471",
                "date": "2026-07-04T10:00:00+00:00",
            }
        ], account_id="acc_1", method="body")
        mgr.apply_messages([
            {
                "to": "Hide My Email <code.alias@icloud.com>",
                "subject": "你的临时 ChatGPT 登录代码",
                "date": "2026-07-04T10:00:00+00:00",
            }
        ], account_id="acc_1", method="headers")
        rows, _ = mgr.list_items(group="all", query="code.alias@icloud.com")
        assert rows[0]["code"] == "969471"
        assert rows[0]["status_message"] == "收到验证码"
    print("  PASS test_inventory_header_rescan_keeps_code_status")


def test_inventory_requires_verification_context_and_clears_false_codes():
    """普通邮件数字和业务编号不能被标成验证码，历史误判应自动清理。"""
    from inventory_manager import InventoryManager, extract_verification_code

    assert extract_verification_code("你的临时 ChatGPT 登录代码\n输入此临时验证码以继续：969471") == "969471"
    assert extract_verification_code("Your ChatGPT verification code is 865561") == "865561"
    assert extract_verification_code("ChatGPT 用の一時ログインコード\n確認コード：388253") == "388253"
    assert extract_verification_code("ChatGPT - 你的新套餐\n管理你的账户，套餐编号 3180") == ""
    assert extract_verification_code("只需几句话，即可焕新你的照片\n活动编号 104239") == ""
    assert extract_verification_code("普通通知\n订单参考号 139419DIDN1") == ""

    with tempfile.TemporaryDirectory() as d:
        mgr = InventoryManager(Path(d) / "inventory.json")
        email = "ordinary.alias@icloud.com"
        mgr.sync_aliases([{"email": email, "account_id": "acc_1"}])
        mgr.update_item(
            email,
            code="3180",
            subject="ChatGPT - 你的新套餐",
            preview="管理你的账户，套餐编号 3180",
            last_received_at="2026-08-11T05:03:56Z",
            status_type="ok",
            status_message="收到验证码",
        )
        rows, _ = mgr.list_items(group="all", query=email)
        assert rows[0]["code"] == ""
        assert rows[0]["status_message"] == "收到邮件，未识别验证码"

        mgr.apply_messages([{
            "to": email,
            "subject": "你的临时登录代码",
            "body": "验证码：456810",
            "date": "2026-08-11T05:10:00Z",
        }], account_id="acc_1", method="test")
        mgr.apply_messages([{
            "to": email,
            "subject": "ChatGPT - 你的新套餐",
            "body": "管理你的账户，套餐编号 3180",
            "date": "2026-08-11T05:11:00Z",
        }], account_id="acc_1", method="test")
        rows, _ = mgr.list_items(group="all", query=email)
        assert rows[0]["code"] == ""
        assert rows[0]["status_message"] == "收到邮件，未识别验证码"
    print("  PASS test_inventory_requires_verification_context_and_clears_false_codes")


def test_tagged_icloud_alias_resolves_to_base_inventory():
    """带加号标签的 iCloud 地址必须命中基础别名，不创建第二套状态。"""
    from inventory_manager import InventoryManager, base_icloud_email_address
    from services.code_inventory_service import _attach_pickup_query

    base = "alias@icloud.com"
    with tempfile.TemporaryDirectory() as d:
        mgr = InventoryManager(Path(d) / "inventory.json")
        mgr.sync_aliases([
            {"email": base, "account_id": "acc_1"},
        ])
        for tagged in (
            "alias+001@icloud.com",
            "alias+sdahhz@icloud.com",
            "alias+abc-123_test@icloud.com",
        ):
            rows, _ = mgr.list_items(group="all", query=tagged)
            rows = _attach_pickup_query(rows, tagged)
            assert base_icloud_email_address(tagged) == base
            assert len(rows) == 1
            assert rows[0]["email"] == base
            assert rows[0]["pickup_email"] == tagged
    print("  PASS test_tagged_icloud_alias_resolves_to_base_inventory")


def test_live_alias_owner_overrides_stale_local_owner():
    """实时苹果别名归属必须覆盖本地创建记录中的旧账号 ID。"""
    from unittest.mock import patch

    import app_core as core
    from inventory_manager import InventoryManager

    email = "owner-order@icloud.com"
    with tempfile.TemporaryDirectory() as d:
        inventory = InventoryManager(Path(d) / "inventory.json")
        with patch.object(core, "_inventory", inventory), \
                patch.object(core, "_read_local_email_rows", return_value=[{"email": email, "account_id": "old"}]), \
                patch.object(core, "_read_alias_cache", return_value={"aliases": [{"email": email, "account_id": "current"}]}), \
                patch.object(core, "_account_lookup", return_value={}):
            core._sync_inventory_from_known()
        rows, _ = inventory.list_items(group="all", query=email)
        assert rows[0]["account_id"] == "current"
    print("  PASS test_live_alias_owner_overrides_stale_local_owner")


def test_all_inboxes_keep_same_uid_from_different_accounts():
    """不同账号的相同 IMAP UID 必须保留为两封邮件。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    accounts = [
        {"id": "acc_1", "status": "active", "icloud_email": "one@icloud.com"},
        {"id": "acc_2", "status": "active", "icloud_email": "two@icloud.com"},
    ]

    def fake_result(acc_id, limit, refresh=False, cache_only=False):
        minute = "02" if acc_id == "acc_2" else "01"
        return {
            "ok": True,
            "account_id": acc_id,
            "emails": [{
                "id": "100",
                "account_id": acc_id,
                "date": f"Tue, 21 Jul 2026 10:{minute}:00 +0800",
            }],
            "count": 1,
            "cached": {},
        }

    with app.test_request_context("/api/inbox?refresh=1&limit=20"):
        with patch.object(mail_service._account_mgr, "list_accounts", return_value=accounts), \
                patch.object(mail_service, "_inbox_account_result", side_effect=fake_result):
            data = mail_service.api_all_inboxes().get_json()

    keys = {f"{message['account_id']}::{message['id']}" for message in data["emails"]}
    assert data["count"] == 2
    assert keys == {"acc_1::100", "acc_2::100"}
    assert [message["account_id"] for message in data["emails"]] == ["acc_2", "acc_1"]
    print("  PASS test_all_inboxes_keep_same_uid_from_different_accounts")


def test_cookie_helper_download_is_valid_zip():
    """Cookie 助手下载接口应返回包含完整扩展文件的 ZIP。"""
    from routes.accounts import api_cookie_helper_download
    from web_ui import app

    with app.test_request_context("/api/cookie-helper/download"):
        response = app.make_response(api_cookie_helper_download())

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert "icloud-hme-cookie-helper.zip" in response.headers.get("Content-Disposition", "")

    with zipfile.ZipFile(io.BytesIO(response.get_data()), "r") as archive:
        names = set(archive.namelist())
        assert "icloud-hme-cookie-helper/manifest.json" in names
        assert "icloud-hme-cookie-helper/popup.html" in names
        assert "icloud-hme-cookie-helper/popup.js" in names
        assert "icloud-hme-cookie-helper/icons/icon128.png" in names
        manifest = json.loads(archive.read("icloud-hme-cookie-helper/manifest.json"))
        assert manifest["manifest_version"] == 3

    print("  PASS test_cookie_helper_download_is_valid_zip")


def test_email_search_uses_owner_when_another_account_is_selected():
    """邮箱查询必须忽略当前下拉框并在全部账号中查找。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    accounts = [
        {"id": "selected", "icloud_email": "selected@icloud.com"},
        {"id": "owner", "icloud_email": "owner@icloud.com"},
    ]
    calls = []

    def fake_check(acc_id, alias, **_kwargs):
        calls.append((acc_id, alias))
        if acc_id == "owner":
            return [{"id": "101", "to": alias, "subject": "Login code"}]
        return []

    with app.test_request_context(
        "/api/inbox/search?alias=target%2Bsdahhz@icloud.com&account_id=selected&limit=10"
    ):
        with patch.object(mail_service, "_mail_account_candidates", return_value=accounts), \
                patch.object(mail_service._account_mgr, "check_alias_mail", side_effect=fake_check), \
                patch.object(mail_service, "_fetch_missing_bodies", side_effect=lambda _acc, rows, **_kw: rows), \
                patch.object(mail_service, "_sync_inventory_from_messages"):
            response = mail_service.api_search_inboxes()

    data = response.get_json()
    assert data["ok"] is True
    assert data["account_id"] == "owner"
    assert data["count"] == 1
    assert data["alias"] == "target+sdahhz@icloud.com"
    assert data["lookup_alias"] == "target@icloud.com"
    assert calls == [("selected", "target@icloud.com"), ("owner", "target@icloud.com")]
    print("  PASS test_email_search_uses_owner_when_another_account_is_selected")


def test_specific_inbox_query_uses_base_for_arbitrary_plus_tag():
    """指定账号收件箱也必须去掉任意加号标签后查询 IMAP。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    with app.test_request_context("/api/accounts/owner/mail/alias+letters@icloud.com?force=1"):
        with patch.object(mail_service._account_mgr, "check_alias_mail", return_value=[]) as check_mail, \
                patch.object(mail_service, "_fetch_missing_bodies", return_value=[]), \
                patch.object(mail_service, "_sync_inventory_from_messages"):
            response = mail_service.api_specific_alias_mail("owner", "alias+letters@icloud.com")

    data = response.get_json()
    assert data["alias"] == "alias+letters@icloud.com"
    assert data["lookup_alias"] == "alias@icloud.com"
    check_mail.assert_called_once_with("owner", "alias@icloud.com", limit=20, days=30, force=True)
    print("  PASS test_specific_inbox_query_uses_base_for_arbitrary_plus_tag")


def test_email_search_frontend_is_global_and_has_stable_busy_state():
    """前端邮箱查询不能携带账号限制，忙碌状态必须先声明。"""
    source = (HERE / "static" / "js" / "inbox.js").read_text(encoding="utf-8")
    assert "var _inboxBusy=false;" in source
    assert "var _inboxSearchBusy=false;" in source
    search_block = source.split("window.searchAliasMail = async function(){", 1)[1].split(
        "window.checkAliasMail = async function(){", 1
    )[0]
    assert "account_id=" not in search_block
    assert "++_inboxRequestSeq" in search_block
    assert "finally" in search_block
    assert search_block.index("_inboxSearchActive=true;") < search_block.index("await api('/api/inbox/search")
    assert "renderInboxMsgs(d.emails||[],esc(alias)+' ('+(d.count||0)+' 封)',accId)" in search_block
    print("  PASS test_email_search_frontend_is_global_and_has_stable_busy_state")


def test_inbox_search_mode_blocks_every_background_refresh_path():
    """搜索框有邮箱时，缓存链、定时器和页面恢复都不得覆盖搜索结果。"""
    source = (HERE / "static" / "js" / "inbox.js").read_text(encoding="utf-8")
    admin_html = (HERE / "templates" / "admin.html").read_text(encoding="utf-8")
    refresh_block = source.split("window.refreshInbox = async function(options){", 1)[1].split(
        "window.setAppPassword = async function", 1
    )[0]
    select_block = source.split("window.updateInboxAccountSelect = function(opts){", 1)[1].split(
        "window.handleInboxAccountChange=function", 1
    )[0]
    assert "function inboxSearchQuery()" in source
    assert "function inboxSearchMode()" in source
    assert "if(inboxSearchMode()&&!options.allowDuringSearch)return Promise.resolve();" in refresh_block
    assert "&&!inboxSearchMode())window.refreshInbox({refresh:true,background:true})" in source
    assert "&&!_inboxBusy&&!inboxSearchMode())window.refreshInbox" in source
    assert "if(!inboxSearchMode())window.refreshInbox({refresh:true,background:true});" in source
    assert select_block.index("if(opts.passive)return;") < select_block.index("var store=useInboxStore(next);")
    assert 'onclick="refreshCurrentInboxView()"' in admin_html
    print("  PASS test_inbox_search_mode_blocks_every_background_refresh_path")


def test_public_pickup_accepts_email_and_returns_latest_two_messages():
    """公开取码只提交邮箱，并只返回最新两封邮件。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    messages = [
        {"id": "1", "date": "2026-08-03T10:01:00+08:00", "subject": "One", "body": "验证码：123451", "from": "a@example.com"},
        {"id": "4", "date": "2026-08-03T10:04:00+08:00", "subject": "Four", "body": "验证码：456789", "from": "a@example.com"},
        {"id": "2", "date": "2026-08-03T10:02:00+08:00", "subject": "Two", "body": "验证码：234567", "from": "a@example.com"},
        {"id": "3", "date": "2026-08-03T10:03:00+08:00", "subject": "Three", "body": "验证码：345678", "from": "a@example.com"},
    ]
    accounts = [{"id": "owner", "icloud_email": "owner@icloud.com"}]

    with app.test_request_context(
        "/api/public/code",
        method="POST",
        json={"email": "target@icloud.com"},
    ):
        with patch.object(mail_service, "_mail_account_candidates", return_value=accounts), \
                patch.object(mail_service, "_cached_pickup_messages", return_value=[]), \
                patch.object(mail_service._account_mgr, "check_alias_mail", return_value=messages), \
                patch.object(mail_service, "_fetch_missing_bodies", side_effect=lambda _acc, rows, **_kw: rows), \
                patch.object(mail_service, "_sync_inventory_from_messages"):
            response = app.make_response(mail_service.api_public_code())

    data = response.get_json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["count"] == 2
    assert [message["id"] for message in data["messages"]] == ["4", "3"]
    assert data["code"] == "456789"
    assert "account_id" not in json.dumps(data)
    print("  PASS test_public_pickup_accepts_email_and_returns_latest_two_messages")


def test_public_pickup_plus_alias_queries_base_address():
    """iCloud 加号地址必须查询基础隐私邮箱，并保留用户输入作为响应邮箱。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    account = {"id": "owner", "icloud_email": "owner@icloud.com"}
    message = {
        "id": "3667",
        "date": "2026-08-02T17:46:11+00:00",
        "to": "Hide My Email <bardic-nock7t@icloud.com>",
        "subject": "ChatGPT - 你的新套餐",
    }
    with app.test_request_context(
        "/api/public/code",
        method="POST",
        json={"email": "bardic-nock7t+001@icloud.com"},
    ):
        with patch.object(mail_service, "_mail_account_candidates", return_value=[account]) as candidates, \
                patch.object(mail_service, "_cached_pickup_messages", return_value=[]), \
                patch.object(mail_service._account_mgr, "check_alias_mail", return_value=[message]) as check_mail, \
                patch.object(mail_service, "_fetch_missing_bodies", side_effect=lambda _acc, rows, **_kw: rows), \
                patch.object(mail_service, "_sync_inventory_from_messages"):
            response = app.make_response(mail_service.api_public_code())

    data = response.get_json()
    assert response.status_code == 200
    assert data["email"] == "bardic-nock7t+001@icloud.com"
    assert data["messages"][0]["id"] == "3667"
    candidates.assert_called_once_with("bardic-nock7t@icloud.com", "")
    check_mail.assert_called_once_with(
        "owner", "bardic-nock7t@icloud.com", limit=2, days=30, force=True
    )
    print("  PASS test_public_pickup_plus_alias_queries_base_address")


def test_public_pickup_cache_reads_matching_inbox_messages():
    """专用别名缓存为空时，必须从账号收件箱缓存筛选对应隐私邮箱。"""
    from unittest.mock import patch

    from services import mail_service

    matching = {
        "id": "3667",
        "to": "Hide My Email <bardic-nock7t@icloud.com>",
        "subject": "ChatGPT - 你的新套餐",
    }
    unrelated = {
        "id": "3668",
        "to": "Hide My Email <other@icloud.com>",
        "subject": "Other",
    }
    with patch.object(mail_service._account_mgr._cache, "get_alias_mail", return_value=[]), \
            patch.object(mail_service._account_mgr._cache, "get_inbox", return_value=[unrelated, matching]):
        messages = mail_service._cached_pickup_messages("owner", "bardic-nock7t@icloud.com")
    assert [message["id"] for message in messages] == ["3667"]
    print("  PASS test_public_pickup_cache_reads_matching_inbox_messages")


def test_public_pickup_has_no_rate_limit():
    """公开取码的连续请求必须全部进入邮件查询。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    account = {"id": "owner", "icloud_email": "owner@icloud.com"}
    message = {
        "id": "1",
        "date": "2026-08-03T10:01:00+08:00",
        "subject": "Code",
        "body": "验证码：123451",
        "from": "a@example.com",
    }
    with app.test_request_context(
        "/api/public/code",
        method="POST",
        json={"email": "target@icloud.com"},
    ):
        with patch.object(mail_service, "_mail_account_candidates", return_value=[account]), \
                patch.object(mail_service, "_cached_pickup_messages", return_value=[]), \
                patch.object(mail_service._account_mgr, "check_alias_mail", return_value=[message]) as check_mail, \
                patch.object(mail_service, "_fetch_missing_bodies", side_effect=lambda _acc, rows, **_kw: rows), \
                patch.object(mail_service, "_sync_inventory_from_messages"):
            statuses = [app.make_response(mail_service.api_public_code()).status_code for _ in range(25)]

    assert statuses == [200] * 25
    assert check_mail.call_count == 25
    print("  PASS test_public_pickup_has_no_rate_limit")


def test_public_pickup_coalesces_concurrent_mail_queries():
    """同一邮箱的并发请求共享一次 IMAP 查询，且每个请求都拿到结果。"""
    import concurrent.futures
    import threading
    import time
    from unittest.mock import patch

    from services import mail_service

    message = {"id": "1", "subject": "Code", "body": "验证码：123451"}
    barrier = threading.Barrier(12)

    def check_mail(*_args, **_kwargs):
        time.sleep(0.15)
        return [message]

    def query(_index):
        barrier.wait()
        return mail_service._query_pickup_messages("owner", "target@icloud.com")

    with mail_service._pickup_query_lock:
        mail_service._pickup_queries.clear()
    with patch.object(mail_service._account_mgr, "check_alias_mail", side_effect=check_mail) as mocked, \
            patch.object(mail_service, "_fetch_missing_bodies", side_effect=lambda _acc, rows, **_kw: rows):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(query, range(12)))

    assert mocked.call_count == 1
    assert all(rows == [message] for rows in results)
    print("  PASS test_public_pickup_coalesces_concurrent_mail_queries")


def test_public_pickup_does_not_show_payment_digits_as_code():
    """普通订阅邮件中的银行卡尾号不能显示成验证码。"""
    from services import mail_service

    subscription = mail_service._public_pickup_message({
        "subject": "ChatGPT - 你的新套餐",
        "body": "付款方式 Visa-6966，订单已完成。",
    })
    verification = mail_service._public_pickup_message({
        "subject": "你的 ChatGPT 临时验证码",
        "body": "输入此临时验证码以继续：774032",
    })
    japanese = mail_service._public_pickup_message({
        "subject": "ChatGPT 用の一時ログインコード",
        "body": "確認コード：388253",
    })
    assert subscription["code"] == ""
    assert verification["code"] == "774032"
    assert japanese["code"] == "388253"
    print("  PASS test_public_pickup_does_not_show_payment_digits_as_code")


def test_public_pickup_removes_tracking_links_from_body():
    """公开取码正文保留可读文字，但不能展开邮件跟踪链接。"""
    from services import mail_service

    message = mail_service._public_pickup_message({
        "subject": "你的 ChatGPT 临时验证码",
        "body": (
            "输入此临时验证码以继续：083685\n"
            "ChatGPT (http://url3243.email.openai.com/ls/click?upn=very-long-token)\n"
            "帮助中心 <https://help.openai.com/en/?tracking=another-token>\n\u200b"
            "ChatGPT 团队"
        ),
    })
    assert message["code"] == "083685"
    assert "输入此临时验证码以继续" in message["body"]
    assert "ChatGPT 团队" in message["body"]
    assert "http://" not in message["body"]
    assert "https://" not in message["body"]
    assert "upn=" not in message["body"]
    assert "\u200b" not in message["body"]
    print("  PASS test_public_pickup_removes_tracking_links_from_body")


def test_pickup_page_only_asks_for_email():
    """公开取码页只显示邮箱输入框。"""
    from web_ui import app

    client = app.test_client()
    html = client.get("/pickup").get_data(as_text=True)
    assert 'id="email"' in html
    assert 'id="pickupKey"' not in html
    assert "取码密钥" not in html
    assert "pickupToken" not in html
    assert "body:JSON.stringify({email:email})" in html
    assert client.get("/pickup").status_code == 200
    assert client.get("/pickup/").status_code == 200
    assert client.get("/code").status_code == 200
    print("  PASS test_pickup_page_only_asks_for_email")


def test_pickup_link_store_reuses_and_rotates_secure_links():
    """同一邮箱复用链接，重新生成时旧令牌立即失效。"""
    from unittest.mock import patch

    from services import mail_service

    email = "bardic-nock7t+001@icloud.com"
    with tempfile.TemporaryDirectory() as temp_dir:
        link_file = Path(temp_dir) / "pickup_links.json"
        with patch.object(mail_service, "PICKUP_LINKS_FILE", link_file), \
                patch.object(mail_service, "_pickup_link_inventory_item", return_value={"email": "bardic-nock7t@icloud.com"}):
            first, error = mail_service.create_pickup_link(email)
            assert error == ""
            assert first["id"].isdigit()
            assert first["created_at"].endswith("Z")
            assert mail_service.resolve_pickup_link(first["id"], first["token"])["email"] == email
            assert mail_service.resolve_pickup_link(first["id"], "wrong") is None

            reused, error = mail_service.create_pickup_link(email)
            assert error == ""
            assert reused["id"] == first["id"]
            assert reused["token"] == first["token"]

            rotated, error = mail_service.create_pickup_link(email, regenerate=True)
            assert error == ""
            assert rotated["id"] != first["id"]
            assert mail_service.resolve_pickup_link(first["id"], first["token"]) is None
            assert mail_service.resolve_pickup_link(rotated["id"], rotated["token"])["email"] == email
    print("  PASS test_pickup_link_store_reuses_and_rotates_secure_links")


def test_pickup_link_allows_trash_item_from_readable_account():
    """垃圾箱只是收码分类，当前可读母号下的邮箱仍可生成取码链接。"""
    from unittest.mock import patch

    from services import mail_service

    email = "cooks.boomer.4w+001@icloud.com"
    row = {
        "email": "cooks.boomer.4w@icloud.com",
        "account_id": "acc_current",
        "active": True,
        "group": "trash",
    }
    accounts = [
        {
            "id": "acc_current",
            "icloud_email": "owner@icloud.com",
            "app_password": "app-password",
        },
        {
            "id": "acc_other_1",
            "icloud_email": "other1@icloud.com",
            "app_password": "app-password",
        },
        {
            "id": "acc_other_2",
            "icloud_email": "other2@icloud.com",
            "app_password": "app-password",
        },
    ]
    with patch.object(mail_service._account_mgr, "list_accounts", return_value=accounts), \
            patch.object(mail_service._inventory, "list_items", return_value=([row], {})):
        assert mail_service._pickup_link_inventory_item(email) == row

    stale = dict(row, account_id="acc_removed")
    with patch.object(mail_service._account_mgr, "list_accounts", return_value=accounts), \
            patch.object(mail_service._inventory, "list_items", return_value=([stale], {})):
        assert mail_service._pickup_link_inventory_item(email) is None
    print("  PASS test_pickup_link_allows_trash_item_from_readable_account")


def test_pickup_batch_generates_multiple_arbitrary_tag_links():
    """批量接口逐个生成完整标签地址，去重并保留单条失败信息。"""
    from unittest.mock import patch

    from inventory_manager import base_icloud_email_address
    from services import mail_service
    from web_ui import app

    base = "alias@icloud.com"
    raw = "\n".join([
        "alias+001@icloud.com",
        "alias+sdahhz@icloud.com",
        "alias+abc-123_test@icloud.com",
        "ALIAS+SDAHHZ@ICLOUD.COM",
        "missing+tag@icloud.com",
        "not-an-email",
    ])

    def inventory_item(email):
        return {"email": base} if base_icloud_email_address(email) == base else None

    with tempfile.TemporaryDirectory() as temp_dir:
        with app.test_request_context(
            "/api/pickup-links/batch",
            method="POST",
            json={"emails": raw},
        ), patch.object(mail_service, "PICKUP_LINKS_FILE", Path(temp_dir) / "pickup_links.json"), \
                patch.object(mail_service, "_pickup_link_inventory_item", side_effect=inventory_item):
            response = app.make_response(mail_service.api_pickup_links_batch())

    data = response.get_json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["count"] == 3
    assert data["failed"] == 2
    assert [row["email"] for row in data["results"]] == [
        "alias+001@icloud.com",
        "alias+sdahhz@icloud.com",
        "alias+abc-123_test@icloud.com",
    ]
    assert {row["lookup_email"] for row in data["results"]} == {base}
    assert len({row["pickup_url"] for row in data["results"]}) == 3
    assert {row["email"] for row in data["errors"]} == {"missing+tag@icloud.com", "not-an-email"}
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    assert "/api/pickup-links/batch" in rules
    print("  PASS test_pickup_batch_generates_multiple_arbitrary_tag_links")


def test_pickup_batch_generates_unique_random_tags_by_quantity():
    """随机模式先生成原邮箱，再追加指定数量且不重复的别名。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    stored = {
        "next_id": 1001,
        "by_email": {},
        "links": {
            "1000": {
                "email": "alias+duplicate1@icloud.com",
                "token": "old-token",
                "active": False,
                "created_at": "2026-08-01T10:00:00",
            },
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        link_file = Path(temp_dir) / "pickup_links.json"
        link_file.write_text(json.dumps(stored), encoding="utf-8")
        with app.test_request_context(
            "/api/pickup-links/batch",
            method="POST",
            json={"emails": "alias@icloud.com", "random_tags": True, "per_email": 2},
        ), patch.object(mail_service, "PICKUP_LINKS_FILE", link_file), patch.object(
            mail_service, "_pickup_link_inventory_item", return_value={"email": "alias@icloud.com"}
        ), patch.object(
            mail_service,
            "_random_pickup_tag",
            side_effect=["duplicate1", "freshone22", "freshone22", "secondtag3"],
        ):
            response = app.make_response(mail_service.api_pickup_links_batch())
        saved = json.loads(link_file.read_text(encoding="utf-8"))

    data = response.get_json()
    assert response.status_code == 200
    assert data["random_tags"] is True
    assert data["per_email"] == 2
    assert [row["email"] for row in data["results"]] == [
        "alias@icloud.com",
        "alias+freshone22@icloud.com",
        "alias+secondtag3@icloud.com",
    ]
    all_emails = [row["email"] for row in saved["links"].values()]
    assert len(all_emails) == len(set(all_emails)) == 4
    print("  PASS test_pickup_batch_generates_unique_random_tags_by_quantity")


def test_pickup_batch_zero_uses_original_email_and_tags_are_eight_chars():
    """额外数量 0 只生成原邮箱，随机标签默认固定为 8 位。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    email = "fed.feature_5w@icloud.com"
    with tempfile.TemporaryDirectory() as temp_dir:
        link_file = Path(temp_dir) / "pickup_links.json"
        with app.test_request_context(
            "/api/pickup-links/batch",
            method="POST",
            json={"emails": email, "random_tags": True, "per_email": 0},
        ), patch.object(mail_service, "PICKUP_LINKS_FILE", link_file), patch.object(
            mail_service, "_pickup_link_inventory_item", return_value={"email": email}
        ):
            response = app.make_response(mail_service.api_pickup_links_batch())

    data = response.get_json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["random_tags"] is False
    assert data["per_email"] == 0
    assert [row["email"] for row in data["results"]] == [email]
    assert len(mail_service._random_pickup_tag()) == 8
    print("  PASS test_pickup_batch_zero_uses_original_email_and_tags_are_eight_chars")


def test_pickup_link_records_are_searchable_and_hide_inactive_links():
    """生成记录按新到旧分页，只展示当前仍有效的链接。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    stored = {
        "next_id": 1003,
        "by_email": {
            "first@icloud.com": "1000",
            "first+tag@icloud.com": "1002",
        },
        "links": {
            "1000": {
                "email": "first@icloud.com",
                "token": "old-token",
                "active": False,
                "created_at": "2026-08-01T10:00:00",
            },
            "1001": {
                "email": "second@icloud.com",
                "token": "second-token",
                "active": True,
                "created_at": "2026-08-02T10:00:00",
            },
            "1002": {
                "email": "first+tag@icloud.com",
                "token": "first-token",
                "active": True,
                "created_at": "2026-08-03T10:00:00",
            },
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        link_file = Path(temp_dir) / "pickup_links.json"
        link_file.write_text(json.dumps(stored), encoding="utf-8")
        with app.test_request_context("/api/pickup-links?q=first&page=1&page_size=20"), \
                patch.object(mail_service, "PICKUP_LINKS_FILE", link_file):
            response = app.make_response(mail_service.api_pickup_links())

    data = response.get_json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["total"] == 1
    assert data["records"] == [{
        "id": "1002",
        "email": "first+tag@icloud.com",
        "pickup_url": "/c/1002?token=first-token",
        "created_at": "2026-08-03T10:00:00",
    }]
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    assert "/api/pickup-links" in rules
    assert app.test_client().get("/api/pickup-links").status_code == 401
    print("  PASS test_pickup_link_records_are_searchable_and_hide_inactive_links")


def test_pickup_link_routes_render_fixed_email_and_auto_refresh():
    """专属链接页固定邮箱，通过固定 JSON API 每三秒自动刷新。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    client = app.test_client()
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    assert "/pickup/<token>/<path:email_addr>" not in rules
    assert "/c/<link_id>" in rules
    assert "/api/public/latest-code/<mailbox_id>" in rules
    assert "/api/pickup-links/for-email/<path:email_addr>" in rules
    with patch.object(mail_service, "resolve_pickup_link", return_value={"id": "1000", "email": "alias+001@icloud.com"}):
        response = client.get("/c/1000?token=valid")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert 'data-pickup-email="alias+001@icloud.com"' in html
    assert 'data-pickup-link-id="1000"' in html
    assert "alias+001@icloud.com" in html
    assert 'id="email"' not in html
    assert 'id="latestCode"' in html
    assert 'id="copyLatestCode"' in html
    assert "/api/public/latest-code/" in html
    assert "setTimeout(refreshLatest,3000)" in html
    assert "prefers-color-scheme:dark" in html
    assert "接口异常，3 秒后重试" in html
    with patch.object(mail_service, "resolve_pickup_link", return_value=None):
        denied = client.get("/c/1000?token=wrong")
    assert denied.status_code == 403
    assert "无权限" in denied.get_data(as_text=True)
    assert "no-store" in denied.headers["Cache-Control"]
    print("  PASS test_pickup_link_routes_render_fixed_email_and_auto_refresh")


def test_public_latest_code_api_uses_shared_pickup_result():
    """固定 API 必须复用公开取码函数，并返回最新六位码及邮件元信息。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    result = {
        "ok": True,
        "email": "alias+001@icloud.com",
        "messages": [
            {"id": "2", "code": "", "date": "2026-08-11T06:00:00Z", "from": "news@example.com", "subject": "普通通知"},
            {"id": "1", "code": "083685", "date": "2026-08-11T05:59:00Z", "from": "ChatGPT <noreply@example.com>", "subject": "你的临时登录代码"},
        ],
        "checked_at": "2026-08-11T06:00:01Z",
    }
    client = app.test_client()
    with patch.object(mail_service, "resolve_pickup_link", return_value={"id": "1000", "email": result["email"]}), \
            patch.object(mail_service, "get_public_pickup_result", return_value=(result, 200)) as shared:
        response = client.get("/api/public/latest-code/1000?token=valid")

    data = response.get_json()
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert data["ok"] is True
    assert data["status"] == "ready"
    assert data["mailbox_id"] == "1000"
    assert data["code"] == "083685"
    assert data["mail_time"] == "2026-08-11T05:59:00Z"
    assert data["sender"] == "ChatGPT <noreply@example.com>"
    assert data["subject"] == "你的临时登录代码"
    shared.assert_called_once_with("alias+001@icloud.com")

    with patch.object(mail_service, "resolve_pickup_link", return_value=None):
        denied = client.get("/api/public/latest-code/1000?token=wrong")
    assert denied.status_code == 403
    assert denied.get_json()["status"] == "unauthorized"

    with patch.object(mail_service, "resolve_pickup_link", return_value={"id": "1000", "email": result["email"]}), \
            patch.object(mail_service, "get_public_pickup_result", return_value=({"ok": False, "error": "没有找到发给这个邮箱的邮件"}, 404)):
        waiting = client.get("/api/public/latest-code/1000?token=valid")
    assert waiting.status_code == 200
    assert waiting.get_json()["status"] == "waiting"
    assert waiting.get_json()["code"] == ""

    with patch.object(mail_service, "resolve_pickup_link", return_value={"id": "1000", "email": result["email"]}), \
            patch.object(mail_service, "get_public_pickup_result", return_value=({"ok": False, "error": "IMAP unavailable"}, 503)):
        retry = client.get("/api/public/latest-code/1000?token=valid")
    assert retry.status_code == 503
    assert retry.get_json()["status"] == "retry"
    print("  PASS test_public_latest_code_api_uses_shared_pickup_result")


def test_pickup_links_can_be_revoked_individually_and_in_batch():
    """失效操作保留历史记录，但旧令牌必须立即不可用。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    stored = {
        "next_id": 1002,
        "by_email": {
            "one@icloud.com": "1000",
            "two@icloud.com": "1001",
        },
        "links": {
            "1000": {"email": "one@icloud.com", "token": "token-one", "active": True, "created_at": "2026-08-01T10:00:00"},
            "1001": {"email": "two@icloud.com", "token": "token-two", "active": True, "created_at": "2026-08-02T10:00:00"},
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        link_file = Path(temp_dir) / "pickup_links.json"
        link_file.write_text(json.dumps(stored), encoding="utf-8")
        with patch.object(mail_service, "PICKUP_LINKS_FILE", link_file):
            revoked, missing = mail_service.revoke_pickup_links(["1000"])
            assert revoked == ["1000"]
            assert missing == []
            assert mail_service.resolve_pickup_link("1000", "token-one") is None

            with app.test_request_context(
                "/api/pickup-links/revoke-batch",
                method="POST",
                json={"link_ids": ["1001", "9999"]},
            ):
                response = app.make_response(mail_service.api_revoke_pickup_links_batch())
            assert response.status_code == 200
            assert response.get_json()["revoked"] == ["1001"]
            assert response.get_json()["missing"] == ["9999"]
            assert mail_service.resolve_pickup_link("1001", "token-two") is None

            saved = json.loads(link_file.read_text(encoding="utf-8"))
            assert saved["links"]["1000"]["active"] is False
            assert saved["links"]["1001"]["active"] is False
            assert saved["links"]["1000"]["revoked_at"]
            assert saved["by_email"] == {}

    rules = {str(rule) for rule in app.url_map.iter_rules()}
    assert "/api/pickup-links/<link_id>" in rules
    assert "/api/pickup-links/revoke-batch" in rules
    assert app.test_client().delete("/api/pickup-links/1000").status_code == 401
    print("  PASS test_pickup_links_can_be_revoked_individually_and_in_batch")


def test_pickup_record_ui_has_single_and_batch_revoke():
    """生成记录支持失效操作、北京时间，并防止误点遮罩关闭。"""
    source = (HERE / "static" / "js" / "code_desk.js").read_text(encoding="utf-8")
    assert "pickupRecordSelectAll" in source
    assert "data-pickup-record-id" in source
    assert "批量失效" in source
    assert "requestRevokePickupLinks" in source
    assert "/api/pickup-links/revoke-batch" in source
    assert "邮箱本身和邮件不会被删除" in source
    assert "formatPickupRecordTime(item.created_at)" in source
    assert 'id="pickupBatchModal" data-static-backdrop="true"' in source
    assert 'id="pickupBatchModal" onclick=' not in source
    assert 'class="pickup-modal-close" title="关闭" aria-label="关闭"' in source
    admin_source = (HERE / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert "dataset.staticBackdrop!=='true'" in admin_source
    assert "BEIJING_TIME_ZONE='Asia/Shanghai'" in admin_source
    css = (HERE / "static" / "css" / "admin.css").read_text(encoding="utf-8")
    assert ".pickup-modal-close{position:absolute;top:14px;right:14px" in css
    assert "confirm(" not in source
    print("  PASS test_pickup_record_ui_has_single_and_batch_revoke")


def test_all_visible_times_use_beijing_timezone():
    """后台和公开取码页的可见时间必须统一按北京时间格式化。"""
    admin = (HERE / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    inbox = (HERE / "static" / "js" / "inbox.js").read_text(encoding="utf-8")
    code_desk = (HERE / "static" / "js" / "code_desk.js").read_text(encoding="utf-8")
    pickup = (HERE / "templates" / "pickup.html").read_text(encoding="utf-8")
    app_core = (HERE / "app_core.py").read_text(encoding="utf-8")
    auto_stock = (HERE / "services" / "auto_stock_service.py").read_text(encoding="utf-8")

    assert "timeZone:BEIJING_TIME_ZONE" in admin
    assert "formatBeijingClock(trigger*1000)" in admin
    assert "formatBeijingDateTime(l.time||'')" in admin
    assert "formatBeijingDateTime(e.created_at||e.createdAt||'')" in inbox
    assert "return formatBeijingMailTime(date)" in inbox
    assert "toLocaleString" not in inbox
    assert "formatBeijingDateTime(item.last_received_at)" in code_desk
    assert "formatBeijingDateStamp(Date.now())" in code_desk
    assert "timeZone:'Asia/Shanghai'" in pickup
    assert "toLocaleString" not in pickup
    assert "_beijing_time(target).strftime('%H:%M')" in app_core
    assert "_beijing_now().strftime('%m%d%H%M')" in app_core
    assert "_beijing_now().strftime('%m%d%H%M')" in auto_stock
    print("  PASS test_all_visible_times_use_beijing_timezone")


def test_legacy_pickup_credentials_are_removed():
    """公开取码不保留旧密钥模型，专属链接使用独立随机令牌。"""
    sources = "\n".join(
        (HERE / path).read_text(encoding="utf-8")
        for path in [
            "app_core.py",
            "inventory_manager.py",
            "routes/accounts.py",
            "routes/inbox.py",
            "routes/pickup.py",
            "services/mail_service.py",
            "templates/pickup.html",
            "static/js/admin.js",
            "static/js/code_desk.js",
        ]
    )
    for old in (
        "MAIL_KEYS_FILE",
        "/api/mail-keys/",
        "邮箱取码密钥",
        "generateCodeKey",
        "codeKeyValue",
        "PICKUP_GROUPS_FILE",
        "pickup_group",
        "pickup-groups",
        "group_id",
        "取码分组",
        "PICKUP_ACCESS_KEY",
        "pickup_access_key",
        "pickupKey",
        "取码密钥",
        "pickup_token",
    ):
        assert old not in sources
    pickup = (HERE / "templates" / "pickup.html").read_text(encoding="utf-8")
    code_desk = (HERE / "static" / "js" / "code_desk.js").read_text(encoding="utf-8")
    assert 'id="key"' not in pickup
    assert 'id="pickupKey"' not in pickup
    assert "最新两封邮件" in pickup
    assert 'class="mail-code-summary"' in pickup
    assert "mail-code-placeholder" in pickup
    assert "index===0?'open'" not in pickup
    assert '<details class="mail-item"' not in pickup
    assert 'id="mailModal"' in pickup
    assert "data-message-index" in pickup
    assert "event.stopPropagation()" in pickup
    assert "'/pickup/'+encodeURIComponent(email)" not in code_desk
    assert "/api/pickup-links/for-email/" in code_desk
    assert "/api/pickup-links/batch" in code_desk
    assert "basePickupEmail" in code_desk
    assert "setCodeSearch" in code_desk
    assert "codeState.group='all'" in code_desk
    assert "生成记录" in code_desk
    assert "&quot;pickup-batch&quot;" not in code_desk
    assert "action==='pickup-batch'" not in code_desk
    assert "下载 TXT" in code_desk
    assert "downloadPickupRecordHistory" in code_desk
    assert "/api/pickup-links?page=" in code_desk
    admin_html = (HERE / "templates" / "admin.html").read_text(encoding="utf-8")
    assert "onclick=\"openPickupBatchModal('')\">批量生成链接</button>" in admin_html
    assert "item.pickup_email||item.email" in code_desk
    assert "取码链接" in code_desk
    assert "email+'----'+absolute" in code_desk
    assert "--------" not in code_desk
    print("  PASS test_legacy_pickup_credentials_are_removed")


def test_batch_selection_uses_store_and_is_not_reset_on_render():
    """批量账号选择必须持久化，刷新不能重新全选或混淆实际创建账号。"""
    source = (HERE / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    render_block = source.split("function renderBatchPanel(){", 1)[1].split(
        "async function execBatchCreate(){", 1
    )[0]
    assert "selectedAccountIds" in source
    assert "setBatchAccountSelected" in render_block
    assert "body.innerHTML" not in render_block
    assert " checked>" not in render_block
    assert "Object.keys(batchState.selectedAccountIds)" in source
    assert "BATCH_SELECTION_KEY='hme.batch.selectedAccountIds.v1'" in source
    assert "localStorage.getItem(BATCH_SELECTION_KEY)" in source
    assert "localStorage.setItem(BATCH_SELECTION_KEY" in source
    assert "saveBatchAccountSelection();" in source
    assert "已选 '+selectedCount+' / 可用 '" in render_block
    assert "开始创建（'+selectedCount+' 个账号）" in render_block
    assert "btn.disabled=batchState.busy||!!state.creating||!selectedCount" in render_block
    print("  PASS test_batch_selection_uses_store_and_is_not_reset_on_render")


def test_batch_creation_uses_spaced_random_delays():
    """批量创建应在别名和账号之间使用分段随机间隔，不再固定 3 秒。"""
    from unittest.mock import patch

    from account_manager import (
        AccountManager,
        BATCH_ACCOUNT_DELAY_RANGE,
        BATCH_ALIAS_DELAY_RANGE,
    )

    mgr = AccountManager.__new__(AccountManager)
    mgr.accounts = {
        "acc_1": {"id": "acc_1", "status": "active"},
        "acc_2": {"id": "acc_2", "status": "active"},
    }
    calls = []

    def create(account_id, count, label, delay_range=None):
        calls.append((account_id, count, label, delay_range))
        return [{"ok": True, "email": f"{account_id}-{i}@icloud.com"} for i in range(count)]

    with patch.object(mgr, "create_aliases_for_account", side_effect=create), patch.object(
        mgr, "_save"
    ), patch("account_manager.random.uniform", return_value=120.0) as uniform, patch(
        "account_manager.time.sleep"
    ) as sleep:
        result = mgr.create_aliases_batch(["acc_1", "acc_2"], 2, label="batch")

    assert set(result) == {"acc_1", "acc_2"}
    assert calls == [
        ("acc_1", 2, "batch", BATCH_ALIAS_DELAY_RANGE),
        ("acc_2", 2, "batch", BATCH_ALIAS_DELAY_RANGE),
    ]
    uniform.assert_called_once_with(*BATCH_ACCOUNT_DELAY_RANGE)
    sleep.assert_called_once_with(120.0)
    print("  PASS test_batch_creation_uses_spaced_random_delays")


def test_auto_stock_config_migrates_to_multiple_accounts():
    """旧单账号配置应迁移为账号数组，并只写入新的多选模型。"""
    from unittest.mock import patch

    import inventory_manager

    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "auto_stock.json"
        config_file.write_text(json.dumps({"enabled": True, "account_id": "acc_2"}), encoding="utf-8")
        with patch.object(inventory_manager, "AUTO_STOCK_FILE", config_file), patch.object(
            inventory_manager, "RESULTS_DIR", Path(temp_dir)
        ):
            migrated = inventory_manager.load_auto_stock_config()
            assert migrated["all_accounts"] is False
            assert migrated["account_ids"] == ["acc_2"]
            assert "account_id" not in migrated

            saved = inventory_manager.save_auto_stock_config({
                "all_accounts": False,
                "account_ids": ["acc_1", "acc_3", "acc_1"],
            })
            stored = json.loads(config_file.read_text(encoding="utf-8"))
            assert saved["account_ids"] == ["acc_1", "acc_3"]
            assert stored["account_ids"] == ["acc_1", "acc_3"]
            assert stored["all_accounts"] is False
            assert "account_id" not in stored
    print("  PASS test_auto_stock_config_migrates_to_multiple_accounts")


def test_auto_stock_only_runs_selected_accounts():
    """自动补货选择两个账号时，不得调用未勾选的账号。"""
    from unittest.mock import patch

    from services import auto_stock_service

    accounts = [
        {"id": "acc_1", "status": "active", "icloud_email": "one@icloud.com"},
        {"id": "acc_2", "status": "active", "icloud_email": "two@icloud.com"},
        {"id": "acc_3", "status": "active", "icloud_email": "three@icloud.com"},
    ]
    config = {
        "enabled": True,
        "all_accounts": False,
        "account_ids": ["acc_1", "acc_3"],
        "prefix": "stock",
        "target": 2,
        "batch": 1,
        "last_run": "",
        "last_error": "",
    }
    called = []

    def create(account_id, count, label):
        called.append(account_id)
        return [{"ok": True, "email": f"{account_id}@icloud.com"}]

    with patch.object(auto_stock_service, "load_auto_stock_config", return_value=dict(config)), patch.object(
        auto_stock_service, "save_auto_stock_config", side_effect=lambda value: value
    ), patch.object(auto_stock_service, "_sync_inventory_from_known"), patch.object(
        auto_stock_service._account_mgr, "list_accounts", return_value=accounts
    ), patch.object(auto_stock_service._account_mgr, "create_aliases_for_account", side_effect=create), patch.object(
        auto_stock_service._inventory, "sync_aliases"
    ):
        result = auto_stock_service.run_auto_stock({})

    assert result["ok"] is True
    assert result["created"] == 2
    assert called == ["acc_1", "acc_3"]
    assert "acc_2" not in called
    print("  PASS test_auto_stock_only_runs_selected_accounts")


def test_auto_stock_frontend_uses_checkbox_account_ids():
    """自动补货前端必须提交复选账号数组，并明确显示选择数量。"""
    source = (HERE / "static" / "js" / "code_desk.js").read_text(encoding="utf-8")
    assert 'id="stockAccount"' not in source
    assert 'id="stockAllAccounts"' in source
    assert 'data-account-id="' in source
    assert "account_ids:" in source
    assert "all_accounts:" in source
    assert "'已选 '+selectedCount+' / '+activeAccounts.length" in source
    assert "请至少勾选一个账号" in source
    print("  PASS test_auto_stock_frontend_uses_checkbox_account_ids")


def test_alias_list_search_keeps_drag_selection_and_link_action():
    """邮箱列表搜索和取码链接动作不能替换现有拖选模型。"""
    source = (HERE / "static" / "js" / "inbox.js").read_text(encoding="utf-8")
    admin_html = (HERE / "templates" / "admin.html").read_text(encoding="utf-8")
    assert 'id="aliasListSearch"' in admin_html
    assert "setAliasListSearch" in source
    assert "createPickupLinksForSelected" in source
    assert "onmousedown=\"startAliasDragSelect" in source
    assert "onmouseenter=\"enterAliasDragSelect" in source
    assert 'onclick=\"event.preventDefault();event.stopPropagation()\"' in source
    assert "onchange=\"toggleAliasSelection" not in source
    print("  PASS test_alias_list_search_keeps_drag_selection_and_link_action")


def test_batch_pickup_links_and_runtime_log_controls_are_wired():
    """批量创建可选同步生成链接，运行日志可读取并清理历史。"""
    admin_html = (HERE / "templates" / "admin.html").read_text(encoding="utf-8")
    admin_js = (HERE / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    accounts_route = (HERE / "routes" / "accounts.py").read_text(encoding="utf-8")
    scheduler_route = (HERE / "routes" / "scheduler.py").read_text(encoding="utf-8")
    assert 'id="batchCreatePickupLinks"' in admin_html
    assert "create_pickup_links:" in admin_js
    assert "create_pickup_links = data.get(\"create_pickup_links\") is True" in accounts_route
    assert "create_pickup_link(row[\"email\"])" in accounts_route
    assert '@bp.route("/api/logs")' in scheduler_route
    assert '@bp.route("/api/logs/cleanup", methods=["POST"])' in scheduler_route
    assert "onclick=\"cleanupLogs()\"" in admin_html
    print("  PASS test_batch_pickup_links_and_runtime_log_controls_are_wired")


def test_pickup_link_statuses_group_arbitrary_tags_by_base_alias():
    """邮箱列表应按母号汇总有效取码链接，并保留实际自定义标签。"""
    from unittest.mock import patch

    from services import mail_service

    stored = {
        "next_id": 1004,
        "by_email": {},
        "links": {
            "1000": {"email": "38.lug.pints+alpha7@icloud.com", "active": True, "created_at": "2026-08-09T10:00:00"},
            "1001": {"email": "38.lug.pints+order_21@icloud.com", "active": True, "created_at": "2026-08-10T10:00:00"},
            "1002": {"email": "38.lug.pints+retired@icloud.com", "active": False, "created_at": "2026-08-11T10:00:00"},
            "1003": {"email": "other+x9-test@icloud.com", "active": True, "created_at": "2026-08-11T11:00:00"},
        },
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        link_file = Path(temp_dir) / "pickup_links.json"
        link_file.write_text(json.dumps(stored), encoding="utf-8")
        with patch.object(mail_service, "PICKUP_LINKS_FILE", link_file):
            statuses = mail_service.active_pickup_link_statuses()

    status = statuses["38.lug.pints@icloud.com"]
    assert status["has_pickup_link"] is True
    assert status["pickup_link_count"] == 2
    assert status["pickup_link_emails"] == [
        "38.lug.pints+alpha7@icloud.com",
        "38.lug.pints+order_21@icloud.com",
    ]
    assert status["pickup_link_created_at"] == "2026-08-10T10:00:00"
    print("  PASS test_pickup_link_statuses_group_arbitrary_tags_by_base_alias")


def test_qq_imap_config_is_fixed_and_connection_is_tested():
    """QQ IMAP 保存时固定安全服务器，并用授权码实际登录测试。"""
    from unittest.mock import patch

    import inventory_manager

    calls = []

    class FakeImap:
        def __init__(self, host, port, **kwargs):
            calls.append(("connect", host, port, bool(kwargs.get("ssl_context"))))

        def login(self, username, password):
            calls.append(("login", username, password))

        def select(self, mailbox, readonly=False):
            calls.append(("select", mailbox, readonly))
            return "OK", [b"321"]

        def logout(self):
            calls.append(("logout",))

    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "mail-forward.config.json"
        with patch.object(inventory_manager, "FORWARD_CONFIG_FILE", config_file), patch.object(
            inventory_manager.imaplib, "IMAP4_SSL", FakeImap
        ):
            saved = inventory_manager.save_forward_config({
                "enabled": True,
                "provider": "qq",
                "host": "wrong.example",
                "port": 143,
                "secure": False,
                "username": "123456@qq.com",
                "password": "qq-imap-auth-code",
                "mailbox": "INBOX",
            })
            result = inventory_manager.test_forward_mail_connection()
            raw = json.loads(config_file.read_text(encoding="utf-8"))

    assert saved["host"] == "imap.qq.com"
    assert saved["port"] == 993
    assert saved["secure"] is True
    assert saved["has_password"] is True
    assert saved["password"] == ""
    assert raw["version"] == 2
    assert raw["profiles"][0]["password"] == "qq-imap-auth-code"
    assert result["ok"] is True
    assert result["message_count"] == 321
    assert calls[:3] == [
        ("connect", "imap.qq.com", 993, True),
        ("login", "123456@qq.com", "qq-imap-auth-code"),
        ("select", '"INBOX"', True),
    ]
    assert calls[-1] == ("logout",)
    print("  PASS test_qq_imap_config_is_fixed_and_connection_is_tested")


def test_qq_imap_pickup_uses_full_tag_and_falls_back_after_icloud():
    """QQ 转发查询应区分完整 +tag，并在 iCloud 无结果时返回最新邮件。"""
    from unittest.mock import patch

    from services import mail_service
    from web_ui import app

    message = {
        "id": "qq-9",
        "date": "2026-08-11T09:00:00+08:00",
        "to": "38.lug.pints+custom77@icloud.com",
        "subject": "你的 ChatGPT 临时验证码",
        "body": "验证码：778899",
    }
    targets = []

    def query_forward(values, limit=100):
        targets.extend(values)
        return {"ok": True, "messages": [message], "count": 1}

    with app.test_request_context(
        "/api/public/code",
        method="POST",
        json={"email": "38.lug.pints+custom77@icloud.com"},
    ), patch.object(mail_service, "_mail_account_candidates", return_value=[]), patch.object(
        mail_service, "load_forward_configs", return_value=[{"enabled": True}]
    ), patch.object(mail_service, "check_forward_mail", side_effect=query_forward), patch.object(
        mail_service, "_sync_inventory_from_messages"
    ):
        response = app.make_response(mail_service.api_public_code())

    data = response.get_json()
    assert response.status_code == 200
    assert data["source"] == "qq_imap"
    assert data["email"] == "38.lug.pints+custom77@icloud.com"
    assert data["code"] == "778899"
    assert targets == ["38.lug.pints+custom77@icloud.com"]
    print("  PASS test_qq_imap_pickup_uses_full_tag_and_falls_back_after_icloud")


def test_forward_imap_configs_are_per_icloud_account_and_keep_secrets():
    """旧 QQ 配置要迁移，多 iCloud 绑定要独立且留空密钥不能覆盖旧值。"""
    from unittest.mock import patch

    import inventory_manager

    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "mail-forward.config.json"
        config_file.write_text(json.dumps({
            "enabled": True,
            "provider": "qq",
            "username": "legacy@qq.com",
            "password": "legacy-code",
            "mailbox": "INBOX",
        }), encoding="utf-8")
        with patch.object(inventory_manager, "FORWARD_CONFIG_FILE", config_file):
            legacy = inventory_manager.load_forward_configs(redact=False)
            first = inventory_manager.save_forward_config({
                "account_id": "acc_one",
                "enabled": True,
                "provider": "qq",
                "username": "one@qq.com",
                "password": "one-code",
                "mailbox": "INBOX",
            })
            inventory_manager.save_forward_config({
                "account_id": "acc_one",
                "enabled": True,
                "provider": "qq",
                "username": "one@qq.com",
                "password": "",
                "mailbox": "INBOX,其他文件夹",
            })
            second = inventory_manager.save_forward_config({
                "account_id": "acc_two",
                "enabled": True,
                "provider": "microsoft",
                "username": "two@outlook.com",
                "client_id": "client-two",
                "tenant": "consumers",
                "refresh_token": "refresh-two",
            })
            profiles = inventory_manager.load_forward_configs(redact=False)
            redacted = inventory_manager.load_forward_configs(redact=True)

    assert len(legacy) == 1
    assert legacy[0]["id"] == "forward_legacy"
    assert legacy[0]["password"] == "legacy-code"
    by_account = {item["account_id"]: item for item in profiles}
    assert set(by_account) == {"", "acc_one", "acc_two"}
    assert by_account["acc_one"]["id"] == first["id"]
    assert by_account["acc_one"]["password"] == "one-code"
    assert by_account["acc_one"]["mailbox"] == "INBOX,其他文件夹"
    assert by_account["acc_two"]["id"] == second["id"]
    assert by_account["acc_two"]["host"] == "outlook.office365.com"
    assert by_account["acc_two"]["auth_type"] == "oauth2"
    assert by_account["acc_two"]["refresh_token"] == "refresh-two"
    redacted_two = next(item for item in redacted if item["account_id"] == "acc_two")
    assert redacted_two["refresh_token"] == ""
    assert redacted_two["has_refresh_token"] is True
    print("  PASS test_forward_imap_configs_are_per_icloud_account_and_keep_secrets")


def test_microsoft_forward_imap_uses_oauth2_xoauth():
    """Microsoft IMAP 必须刷新 OAuth2 token 并以 XOAUTH2 登录。"""
    from unittest.mock import patch

    import inventory_manager

    calls = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "access-token", "refresh_token": "rotated-token"}

    class FakeImap:
        def __init__(self, host, port, **kwargs):
            calls.append(("connect", host, port, bool(kwargs.get("ssl_context"))))

        def authenticate(self, mechanism, callback):
            calls.append(("authenticate", mechanism, callback(b"")))

        def select(self, mailbox, readonly=False):
            calls.append(("select", mailbox, readonly))
            return "OK", [b"88"]

        def logout(self):
            calls.append(("logout",))

    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "mail-forward.config.json"
        with patch.object(inventory_manager, "FORWARD_CONFIG_FILE", config_file), patch.object(
            inventory_manager.imaplib, "IMAP4_SSL", FakeImap
        ), patch.object(inventory_manager.requests, "post", return_value=FakeResponse()) as post:
            saved = inventory_manager.save_forward_config({
                "account_id": "acc_ms",
                "enabled": True,
                "provider": "microsoft",
                "username": "owner@outlook.com",
                "client_id": "client-id",
                "tenant": "consumers",
                "refresh_token": "refresh-token",
            })
            result = inventory_manager.test_forward_mail_connection(profile_id=saved["id"])
            raw = inventory_manager.load_forward_config(redact=False, profile_id=saved["id"])

    assert result["ok"] is True
    assert result["message_count"] == 88
    assert post.call_args.args[0].endswith("/consumers/oauth2/v2.0/token")
    assert calls[0] == ("connect", "outlook.office365.com", 993, True)
    assert calls[1][0:2] == ("authenticate", "XOAUTH2")
    assert b"owner@outlook.com" in calls[1][2]
    assert b"Bearer access-token" in calls[1][2]
    assert raw["refresh_token"] == "rotated-token"
    print("  PASS test_microsoft_forward_imap_uses_oauth2_xoauth")


def test_forward_imap_scans_only_targets_bound_to_each_icloud_account():
    """每条转发邮箱配置只能匹配其绑定 iCloud 账号的目标邮箱。"""
    from unittest.mock import patch

    import inventory_manager

    class FakeImap:
        def __init__(self, host, port, **kwargs):
            self.username = ""

        def login(self, username, password):
            self.username = username

        def select(self, mailbox, readonly=False):
            return "OK", [b"1"]

        def search(self, charset, criteria):
            return "OK", [b"1"]

        def fetch(self, msg_id, query):
            target = "one.alias@icloud.com" if self.username == "one@qq.com" else "two.alias@icloud.com"
            raw = (
                f"To: {target}\r\n"
                "From: noreply@example.com\r\n"
                "Subject: verification\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n"
                "code 123456"
            ).encode("utf-8")
            return "OK", [(b"RFC822", raw)]

        def logout(self):
            return None

    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "mail-forward.config.json"
        with patch.object(inventory_manager, "FORWARD_CONFIG_FILE", config_file), patch.object(
            inventory_manager.imaplib, "IMAP4_SSL", FakeImap
        ):
            inventory_manager.save_forward_config({
                "account_id": "acc_one", "enabled": True, "provider": "qq",
                "username": "one@qq.com", "password": "one-code",
            })
            inventory_manager.save_forward_config({
                "account_id": "acc_two", "enabled": True, "provider": "qq",
                "username": "two@qq.com", "password": "two-code",
            })
            result = inventory_manager.check_forward_mail({
                "acc_one": ["one.alias@icloud.com"],
                "acc_two": ["two.alias@icloud.com"],
            })

    assert result["ok"] is True
    assert result["profiles_checked"] == 2
    assert result["count"] == 2
    by_account = {message["account_id"]: message for message in result["messages"]}
    assert "one.alias@icloud.com" in by_account["acc_one"]["to"]
    assert "two.alias@icloud.com" in by_account["acc_two"]["to"]
    assert by_account["acc_one"]["forward_provider"] == "qq"
    assert by_account["acc_two"]["forward_provider"] == "qq"
    print("  PASS test_forward_imap_scans_only_targets_bound_to_each_icloud_account")


def test_multi_alias_search_forward_bindings_and_scheduler_countdown_are_wired():
    """批量查找、账号绑定 IMAP 与调度倒计时入口必须完整连通。"""
    inbox = (HERE / "static" / "js" / "inbox.js").read_text(encoding="utf-8")
    code_desk = (HERE / "static" / "js" / "code_desk.js").read_text(encoding="utf-8")
    admin = (HERE / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    admin_html = (HERE / "templates" / "admin.html").read_text(encoding="utf-8")
    routes = (HERE / "routes" / "inventory.py").read_text(encoding="utf-8")

    assert 'onclick="openAliasBatchSearch()"' in admin_html
    assert "function parseAliasBatchQueries(value)" in inbox
    assert "window.applyAliasBatchSearch=function(selectMatches)" in inbox
    assert "matches.forEach(function(row){_aliasSelection[aliasRowKey(row)]=true;});" in inbox
    assert "window.bulkDeleteAliases" in inbox
    assert "_forwardProfiles=(d&&d.configs)||[]" in code_desk
    assert 'id="fwAccount"' in code_desk
    assert "startMicrosoftForwardAuth" in code_desk
    assert "/microsoft/start" in routes and "/microsoft/poll" in routes
    assert "Number(state.next_trigger||0)" in admin
    assert "秒后创建" in admin
    assert "setInterval(refreshSchedulerCountdown,1000)" in admin
    print("  PASS test_multi_alias_search_forward_bindings_and_scheduler_countdown_are_wired")


def test_random_tag_quantity_link_badge_wide_search_and_sticky_inbox_are_wired():
    """随机数量、链接标记、宽搜索框和收件箱选择持久化必须同时保留。"""
    code_desk = (HERE / "static" / "js" / "code_desk.js").read_text(encoding="utf-8")
    inbox = (HERE / "static" / "js" / "inbox.js").read_text(encoding="utf-8")
    css = (HERE / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    assert 'id="pickupAliasCount"' in code_desk
    assert "额外别名数量" in code_desk
    assert "random_tags:perEmail>0" in code_desk
    assert "per_email:perEmail" in code_desk
    assert 'min="0" max="100"' in code_desk
    assert "原邮箱始终生成" in code_desk
    assert "pickupAliasTag" not in code_desk
    assert "applyPickupAliasTag" not in code_desk
    assert "自己的加号标签" not in inbox
    assert "原邮箱始终生成，数量表示额外 8 位随机别名个数" in inbox
    assert "pickup_link_emails" in inbox
    assert "已生成取码链接" in inbox
    assert "pickup-links-updated" in inbox
    assert "INBOX_SELECTION_KEY='hme.inbox.selectedAccountId.v1'" in inbox
    assert "if(!inboxSearchMode())window.refreshInbox" in inbox
    assert "onmousedown=\"startAliasRowDragSelect" in inbox
    assert "onchange=\"toggleAliasSelection" not in inbox
    assert "#aliasListSearch{height:42px" in css
    assert "min-width:360px" in css
    assert ".alias-pickup-state" in css
    print("  PASS test_random_tag_quantity_link_badge_wide_search_and_sticky_inbox_are_wired")


if __name__ == "__main__":
    tests = [
        ("parse_cookie_header_string", test_parse_cookie_header_string),
        ("parse_cookie_json", test_parse_cookie_json),
        ("parse_empty_input", test_parse_empty_input),
        ("derive_icloud_email_primary", test_derive_icloud_email_primary),
        ("derive_icloud_email_appleid_is_icloud", test_derive_icloud_email_appleid_is_icloud),
        ("derive_icloud_email_third_party", test_derive_icloud_email_third_party),
        ("mail_cache_basic", test_mail_cache_basic),
        ("strip_html", test_strip_html),
        ("strip_html_with_link", test_strip_html_with_link),
        ("icloud_hme_account_info", test_icloud_hme_account_info),
        ("inventory_received_mail_marks_finished", test_inventory_received_mail_marks_finished),
        ("inventory_header_rescan_keeps_code_status", test_inventory_header_rescan_keeps_code_status),
        ("inventory_requires_verification_context_and_clears_false_codes", test_inventory_requires_verification_context_and_clears_false_codes),
        ("tagged_icloud_alias_resolves_to_base_inventory", test_tagged_icloud_alias_resolves_to_base_inventory),
        ("live_alias_owner_overrides_stale_local_owner", test_live_alias_owner_overrides_stale_local_owner),
        ("all_inboxes_keep_same_uid_from_different_accounts", test_all_inboxes_keep_same_uid_from_different_accounts),
        ("cookie_helper_download_is_valid_zip", test_cookie_helper_download_is_valid_zip),
        ("email_search_uses_owner_when_another_account_is_selected", test_email_search_uses_owner_when_another_account_is_selected),
        ("specific_inbox_query_uses_base_for_arbitrary_plus_tag", test_specific_inbox_query_uses_base_for_arbitrary_plus_tag),
        ("email_search_frontend_is_global_and_has_stable_busy_state", test_email_search_frontend_is_global_and_has_stable_busy_state),
        ("inbox_search_mode_blocks_every_background_refresh_path", test_inbox_search_mode_blocks_every_background_refresh_path),
        ("public_pickup_accepts_email_and_returns_latest_two_messages", test_public_pickup_accepts_email_and_returns_latest_two_messages),
        ("public_pickup_plus_alias_queries_base_address", test_public_pickup_plus_alias_queries_base_address),
        ("public_pickup_cache_reads_matching_inbox_messages", test_public_pickup_cache_reads_matching_inbox_messages),
        ("public_pickup_has_no_rate_limit", test_public_pickup_has_no_rate_limit),
        ("public_pickup_coalesces_concurrent_mail_queries", test_public_pickup_coalesces_concurrent_mail_queries),
        ("public_pickup_does_not_show_payment_digits_as_code", test_public_pickup_does_not_show_payment_digits_as_code),
        ("public_pickup_removes_tracking_links_from_body", test_public_pickup_removes_tracking_links_from_body),
        ("pickup_page_only_asks_for_email", test_pickup_page_only_asks_for_email),
        ("pickup_link_store_reuses_and_rotates_secure_links", test_pickup_link_store_reuses_and_rotates_secure_links),
        ("pickup_link_allows_trash_item_from_readable_account", test_pickup_link_allows_trash_item_from_readable_account),
        ("pickup_batch_generates_multiple_arbitrary_tag_links", test_pickup_batch_generates_multiple_arbitrary_tag_links),
        ("pickup_batch_generates_unique_random_tags_by_quantity", test_pickup_batch_generates_unique_random_tags_by_quantity),
        ("pickup_batch_zero_uses_original_email_and_tags_are_eight_chars", test_pickup_batch_zero_uses_original_email_and_tags_are_eight_chars),
        ("pickup_link_records_are_searchable_and_hide_inactive_links", test_pickup_link_records_are_searchable_and_hide_inactive_links),
        ("pickup_link_routes_render_fixed_email_and_auto_refresh", test_pickup_link_routes_render_fixed_email_and_auto_refresh),
        ("public_latest_code_api_uses_shared_pickup_result", test_public_latest_code_api_uses_shared_pickup_result),
        ("pickup_links_can_be_revoked_individually_and_in_batch", test_pickup_links_can_be_revoked_individually_and_in_batch),
        ("pickup_record_ui_has_single_and_batch_revoke", test_pickup_record_ui_has_single_and_batch_revoke),
        ("all_visible_times_use_beijing_timezone", test_all_visible_times_use_beijing_timezone),
        ("legacy_pickup_credentials_are_removed", test_legacy_pickup_credentials_are_removed),
        ("batch_selection_uses_store_and_is_not_reset_on_render", test_batch_selection_uses_store_and_is_not_reset_on_render),
        ("batch_creation_uses_spaced_random_delays", test_batch_creation_uses_spaced_random_delays),
        ("auto_stock_config_migrates_to_multiple_accounts", test_auto_stock_config_migrates_to_multiple_accounts),
        ("auto_stock_only_runs_selected_accounts", test_auto_stock_only_runs_selected_accounts),
        ("auto_stock_frontend_uses_checkbox_account_ids", test_auto_stock_frontend_uses_checkbox_account_ids),
        ("alias_list_search_keeps_drag_selection_and_link_action", test_alias_list_search_keeps_drag_selection_and_link_action),
        ("batch_pickup_links_and_runtime_log_controls_are_wired", test_batch_pickup_links_and_runtime_log_controls_are_wired),
        ("pickup_link_statuses_group_arbitrary_tags_by_base_alias", test_pickup_link_statuses_group_arbitrary_tags_by_base_alias),
        ("qq_imap_config_is_fixed_and_connection_is_tested", test_qq_imap_config_is_fixed_and_connection_is_tested),
        ("qq_imap_pickup_uses_full_tag_and_falls_back_after_icloud", test_qq_imap_pickup_uses_full_tag_and_falls_back_after_icloud),
        ("forward_imap_configs_are_per_icloud_account_and_keep_secrets", test_forward_imap_configs_are_per_icloud_account_and_keep_secrets),
        ("microsoft_forward_imap_uses_oauth2_xoauth", test_microsoft_forward_imap_uses_oauth2_xoauth),
        ("forward_imap_scans_only_targets_bound_to_each_icloud_account", test_forward_imap_scans_only_targets_bound_to_each_icloud_account),
        ("multi_alias_search_forward_bindings_and_scheduler_countdown_are_wired", test_multi_alias_search_forward_bindings_and_scheduler_countdown_are_wired),
        ("random_tag_quantity_link_badge_wide_search_and_sticky_inbox_are_wired", test_random_tag_quantity_link_badge_wide_search_and_sticky_inbox_are_wired),
    ]
    
    passed = 0
    failed = 0
    
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            failed += 1
    
    print(f"\n{'='*40}")
    print(f"结果: {passed} 通过, {failed} 失败")
    
    if failed:
        sys.exit(1)
