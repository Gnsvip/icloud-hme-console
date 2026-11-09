"""Read family and iCloud+ state using the web protocols documented by pyicloud.

No membership or billing mutations. See docs/family-icloud-plus.md for the
research and the distinction between web sessions and native mmeAuthToken.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import math
import re
from urllib.parse import urlparse

import requests

from icloud_hme import ICloudHME


class BenefitsError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return value
    return None


def _text(value):
    return value[:240] if isinstance(value, str) else ""


def _request(client, method, url, dsid):
    try:
        response = client.session.request(
            method, url, params={"dsid": dsid},
            headers={"Origin": client.origin, "Referer": client.origin + "/", "Accept": "application/json"},
            timeout=(5, 12), allow_redirects=False,
        )
        if response.status_code in (401, 403, 421):
            raise BenefitsError("Apple 登录状态已失效或无权查询，请重新登录此账号。")
        if 300 <= response.status_code < 400:
            raise BenefitsError("Apple 返回了区域重定向，请重新登录并识别账号区域。")
        if not response.ok:
            raise BenefitsError(f"Apple 暂时无法提供此项信息（HTTP {response.status_code}）。")
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is False or data.get("error"):
            raise BenefitsError("Apple 返回的信息不完整，请稍后刷新。")
        return data
    except requests.RequestException:
        raise BenefitsError("连接 Apple 超时或网络不可用，请稍后刷新。") from None
    except ValueError:
        raise BenefitsError("Apple 返回了无法识别的数据，请稍后刷新。") from None


def _family(data, dsid):
    if type(data.get("isMemberOfFamily")) is not bool:
        raise BenefitsError("Apple 未返回有效的家庭状态，暂时无法判断是否已加入。")
    joined = data["isMemberOfFamily"]
    raw_members = data.get("familyMembers", [])
    if not isinstance(raw_members, list) or (joined and not raw_members):
        raise BenefitsError("Apple 未返回完整的家庭成员列表。")
    family = data.get("family") or {}
    if not isinstance(family, dict):
        raise BenefitsError("Apple 未返回有效的家庭信息。")
    organizer = str(family.get("organizer") or "")
    members = []
    for member in raw_members:
        if not isinstance(member, dict) or not member.get("dsid"):
            raise BenefitsError("Apple 未返回完整的家庭成员信息。")
        member_id = str(member["dsid"])
        members.append({
            "name": _text(member.get("fullName")),
            "apple_id": _text(member.get("appleId")),
            "is_self": member_id == dsid,
            "is_organizer": member_id == organizer,
        })
    invitations = data.get("familyInvitations")
    return {
        "is_member": joined, "is_organizer": organizer == dsid,
        "members": members,
        "invitation_count": len(invitations) if isinstance(invitations, list) else None,
    }


def _storage(data, _dsid):
    usage = data.get("storageUsageInfo")
    if not isinstance(usage, dict):
        raise BenefitsError("Apple 未返回有效的空间用量。")
    total = _number(usage.get("totalStorageInBytes"))
    used = _number(usage.get("usedStorageInBytes"))
    if total is None or used is None:
        raise BenefitsError("Apple 未返回完整的空间用量。")
    return {"total_bytes": total, "used_bytes": used}


def _subscription(data, _dsid):
    summary = data.get("summary")
    if not isinstance(summary, dict) or type(summary.get("includedInPlan")) is not bool:
        raise BenefitsError("Apple 未返回有效的订阅状态。")
    sources = []
    for field, label in (
        ("includedWithAccountPurchasedPlan", "个人订阅"),
        ("includedWithSharedPlan", "家庭共享"),
        ("includedWithAppleOnePlan", "Apple One"),
        ("includedWithCompedPlan", "赠送方案"),
        ("includedWithManagedPlan", "管理方案"),
    ):
        item = data.get(field)
        if isinstance(item, dict) and item.get("includedInPlan") is True:
            sources.append(label)
    return {"included": summary["includedInPlan"], "sources": sources,
            "storage_limit": _number(summary.get("limit")),
            "storage_unit": summary.get("limitUnits") if summary.get("limitUnits") in ("GIB", "TIB") else None}


def read_benefits(manager, account_id):
    account = manager.get_account(account_id)
    if not account:
        raise BenefitsError("账号不存在，请刷新账号列表。", 404)
    cookies = dict(account.get("cookies") or {})
    if not cookies:
        raise BenefitsError("此账号尚未登录 Apple，请先重新登录。", 409)
    client = ICloudHME(cookies, host=account.get("host", "icloud.com"), verbose=False)
    try:
        try:
            validation = client.validate_session(timeout=12, max_attempts=1, require_hme=False)
        except Exception:
            raise BenefitsError("无法验证 Apple 登录状态，请重新登录此账号；网络异常时可稍后刷新。") from None
        info = validation.get("dsInfo") or {}
        dsid = str(info.get("dsid") or "")
        if not re.fullmatch(r"[0-9]{1,30}", dsid):
            raise BenefitsError("Apple 未返回有效的账号身份，请重新登录。")
        # Requests have their own sessions; concurrent reads never share a mutable cookie jar.
        cookies = client.session.cookies.get_dict()
        host = client.host
        try:
            service_url = str(validation.get("webservices", {}).get("account", {}).get("url") or "")
            parsed = urlparse(service_url)
            allowed_service = (parsed.scheme == "https" and parsed.port in (None, 443)
                               and not parsed.username and not parsed.password
                               and not parsed.query and not parsed.fragment and parsed.path in ("", "/")
                               and re.fullmatch(r"(?:p[0-9]+-)?setup\." + re.escape(host), parsed.hostname or ""))
        except (ValueError, AttributeError, TypeError):
            allowed_service = False
        service_url = service_url.rstrip("/") if allowed_service else None
    finally:
        client.session.close()

    def read_section(section):
        name, method, url, parse = section
        if not url:
            return name, {"ok": False, "error": "Apple 未提供此区域的账号查询服务。"}
        child = ICloudHME(cookies, host=host, verbose=False)
        try:
            return name, {"ok": True, **parse(_request(child, method, url, dsid), dsid)}
        except BenefitsError as exc:
            return name, {"ok": False, "error": str(exc)}
        finally:
            child.session.close()

    sections = (
        ("family", "GET", service_url + "/setup/web/family/getFamilyDetails" if service_url else None, _family),
        ("storage", "POST", service_url + "/setup/ws/1/storageUsageInfo" if service_url else None, _storage),
        ("subscription", "GET", f"https://gatewayws.{host}/acsegateway/v3/accounts/{dsid}/subscriptions/features/cloud.storage/plan-summary", _subscription),
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        result = dict(pool.map(read_section, sections))
    hme = info.get("isHideMyEmailSubscriptionActive")
    return {"ok": True, "account_id": account_id, "host": host,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "hide_my_email": hme if type(hme) is bool else None, **result}
