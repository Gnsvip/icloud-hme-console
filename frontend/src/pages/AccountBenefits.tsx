import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { api, enc, stamp, type Row } from "@/lib/api";
import { Button, ErrorNotice, Field, Loading, Modal } from "@/components/common";

export function appleFamilyInvitation(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "https:" || url.username || url.password || url.port ||
        !["setup.icloud.com", "setup.icloud.com.cn"].includes(url.hostname) ||
        url.pathname !== "/family/messages" || url.searchParams.get("aaaction") !== "showFamilyInvite") return null;
    const code = url.searchParams.get("inviteCode");
    if (!code || code === "organizer_create") return null;
    return url.href;
  } catch { return null; }
}

function bytes(value: number) {
  const unit = value >= 1024 ** 4 ? "TB" : "GB";
  const number = value / 1024 ** (unit === "TB" ? 4 : 3);
  return `${number.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${unit}`;
}

function AppleLink({ href, children }: { href: string; children: ReactNode }) {
  return <a className="text-link" href={href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{children}<ExternalLink size={14} /></a>;
}

export function AccountBenefits({ account, close }: { account: Row; close: () => void }) {
  const [invitation, setInvitation] = useState("");
  const [tab, setTab] = useState("family");
  const query = useQuery({
    queryKey: ["account-benefits", account.id],
    queryFn: ({ signal }) => api(`/api/accounts/${enc(account.id)}/benefits`, { signal }),
    retry: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false,
  });
  const data = query.data;
  const family = data?.family;
  const plan = data?.subscription;
  const storage = data?.storage;
  const host = data?.host || (account.host === "icloud.com.cn" ? "icloud.com.cn" : "icloud.com");
  const invitationUrl = appleFamilyInvitation(invitation);
  return <Modal title="家庭共享与 iCloud+" description={`${account.name} · ${account.real_email || account.icloud_email || "iCloud 账号"}`} close={close} wide>
    <div className="benefits-toolbar">
      <span className="muted">{data ? `查询于 ${stamp(data.checked_at)}` : "从 Apple 查询当前账号"}{query.isError && data ? " · 刷新失败，以下为上次结果" : ""}</span>
      <Button size="sm" variant="outline" disabled={query.isFetching} onClick={() => query.refetch()}><RefreshCw className={query.isFetching ? "spin" : ""} />{query.isFetching ? "查询中…" : "刷新状态"}</Button>
    </div>
    <ErrorNotice error={query.error} />
    {query.isPending ? <Loading /> : data && <div className="benefits-overview">
      <section><span className="muted">家庭共享</span><strong>{family?.ok ? family.is_member ? `已加入 · ${family.members.length} 人` : "尚未加入家庭" : "暂时无法查询"}</strong>{family?.ok && family.is_member && <small>{family.is_organizer ? "你是组织者" : "你是家庭成员"}</small>}</section>
      <section><span className="muted">iCloud+ 来源</span><strong>{plan?.ok ? plan.sources.length ? plan.sources.join("、") : plan.included ? "Apple 未注明来源" : "未检测到付费方案" : "暂时无法查询"}</strong><small>隐藏邮件地址：{data.hide_my_email === true ? "已启用" : data.hide_my_email === false ? "未启用" : "未知"}</small></section>
      <section><span className="muted">iCloud 空间</span><strong>{storage?.ok ? bytes(storage.total_bytes) : "暂时无法查询"}</strong>{storage?.ok && <small>已用 {bytes(storage.used_bytes)}</small>}</section>
    </div>}
    <div className="benefits-tabs" role="tablist" aria-label="家庭与方案操作">
      <button role="tab" id="benefits-family-tab" aria-controls="benefits-family" aria-selected={tab === "family"} onClick={() => setTab("family")}>家庭成员与加入</button>
      <button role="tab" id="benefits-plan-tab" aria-controls="benefits-plan" aria-selected={tab === "plan"} onClick={() => setTab("plan")}>开通或升级 iCloud+</button>
    </div>
    {tab === "family" ? <section className="benefits-content" id="benefits-family" role="tabpanel" aria-labelledby="benefits-family-tab">
      {family?.ok === false && <ErrorNotice error={family.error} />}
      {family?.ok && family.is_member && <ul className="benefits-members" aria-label="家庭成员">
        {family.members.map((member: Row, index: number) => <li key={index}><div><strong>{member.name || member.apple_id || "家庭成员"}</strong><small>{member.apple_id}</small></div><span>{member.is_self ? "本人 · " : ""}{member.is_organizer ? "组织者" : "成员"}</span></li>)}
      </ul>}
      {!!family?.invitation_count && <p>Apple 返回了 {family.invitation_count} 条家庭邀请，请在邀请邮件或设备的“设置 → 你的姓名 → 邀请”中处理。</p>}
      <p className="muted">让组织者发送家庭邀请，再在 Apple 邀请页面或设备上确认加入。当前工作台可查询家庭状态，暂不支持直接接受邀请。</p>
      <Field label="Apple 家庭邀请链接（可选）" hint="粘贴邀请中的 setup.icloud.com/family/messages 链接，仅在当前页面使用。">
        <input type="url" autoComplete="off" value={invitation} onChange={(e) => setInvitation(e.target.value)} placeholder="https://setup.icloud.com/family/messages?…" />
      </Field>
      {invitation.trim() && !invitationUrl && <p className="field-error" role="alert">这不是支持的 Apple 家庭邀请链接，请从原始邀请邮件或短信打开。</p>}
      <div className="benefits-links">
        {invitationUrl && <AppleLink href={invitationUrl}>在 Apple 打开邀请</AppleLink>}
        <AppleLink href="https://support.apple.com/zh-cn/108380">查看加入家庭步骤</AppleLink>
      </div>
    </section> : <section className="benefits-content" id="benefits-plan" role="tabpanel" aria-labelledby="benefits-plan-tab">
      {plan?.ok === false && <ErrorNotice error={plan.error} />}
      {storage?.ok === false && <ErrorNotice error={storage.error} />}
      {plan?.sources?.includes("家庭共享") && <p>此账号已通过家庭共享使用 iCloud+。需要更多空间时，可先让共享方案的订阅者升级。</p>}
      <p>打开 Apple 方案页面后选择容量、查看当前价格并确认付款。若网页要求在设备继续，可使用 iPhone、iPad、Mac 或 Windows 版 iCloud 完成开通。</p>
      <p className="muted">Apple 页面或设备的登录账号可能与工作台不同，请核对为 {account.real_email || account.icloud_email || account.name}。付款成功后返回刷新状态。</p>
      <div className="benefits-links">
        <Button asChild><a href={`https://www.${host}/plan/`} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">前往 Apple 开通 / 管理方案<ExternalLink size={14} /></a></Button>
        <AppleLink href="https://support.apple.com/zh-cn/108349">各设备开通步骤</AppleLink>
      </div>
      <small className="muted">当前工作台不直接提交订单或扣款，订阅结果以 Apple 确认为准。</small>
    </section>}
  </Modal>;
}
