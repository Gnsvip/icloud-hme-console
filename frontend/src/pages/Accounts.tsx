import { useBackgroundTasks } from "@/components/BackgroundTasks";
import { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Cloud,
  Download,
  Edit3,
  KeyRound,
  Plus,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { enc, post, type Row } from "@/lib/api";
import {
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Modal,
  Pill,
  Pager,
  SearchBox,
  Submit,
} from "@/components/common";
import { PageHead } from "@/components/PageHead";
import { AppleLoginForm } from "./AppleLogin";
import { AccountBenefits } from "./AccountBenefits";
export function AccountForm({
  account, close, done,
}: { account?: Row; close: () => void; done: () => void }) {
  const [mode, setMode] = useState(account ? "cookie" : "apple");
  if (mode === "apple") return <AppleLoginForm close={close} done={done} useCookie={() => setMode("cookie")} />;
  return <CookieAccountForm account={account} close={close} done={done} useApple={!account ? () => setMode("apple") : undefined} />;
}
function CookieAccountForm({
  account,
  close,
  done,
  useApple,
}: {
  account?: Row;
  close: () => void;
  done: () => void;
  useApple?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal
      title={account ? "账号设置" : "添加 iCloud 账号"}
      description={
        account
          ? "更新账号名称、区域或收件配置。密码留空将保留原值。"
          : "使用 iCloud Cookie 连接账号。设置 App 专用密码后可读取邮件。"
      }
      close={() => !busy && close()}
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const data = Object.fromEntries(new FormData(e.currentTarget)) as Row;
          setBusy(true);
          setError(null);
          try {
            if (
              account &&
              data.icloud_email !== (account.icloud_email || "") &&
              !data.app_password
            )
              throw new Error(
                "修改收件邮箱时，请同时填写 App 专用密码以验证连接",
              );
            if (!account) {
              await post("/api/accounts/add", data);
            } else {
              if (data.name !== account.name)
                await post(`/api/accounts/${enc(account.id)}/rename`, {
                  name: data.name,
                });
              if (data.host !== account.host)
                await post(`/api/accounts/${enc(account.id)}/host`, {
                  host: data.host,
                });
              if (data.app_password)
                await post(`/api/accounts/${enc(account.id)}/app-password`, {
                  app_password: data.app_password,
                  icloud_email: data.icloud_email,
                });
            }
            toast.success("账号信息已保存");
            done();
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="form-grid">
          <Field label="账号名称">
            <input
              name="name"
              required
              defaultValue={account?.name || ""}
              placeholder="例如：个人账号"
            />
          </Field>
          <Field label="账号区域">
            <select name="host" defaultValue={account?.host || "icloud.com"}>
              <option value="icloud.com">国际区 iCloud</option>
              <option value="icloud.com.cn">中国区 iCloud</option>
            </select>
          </Field>
        </div>
        {!account && (
          <Field
            label="iCloud Cookie"
            hint="支持 Cookie Header 字符串或 JSON。"
          >
            <textarea
              name="cookie_input"
              rows={4}
              required
              placeholder="粘贴 Cookie…"
              spellCheck={false}
            />
          </Field>
        )}
        <Field
          label="iCloud 收件邮箱"
          hint="填写 @icloud.com、@me.com 或 @mac.com 邮箱；修改时需同时填写 App 专用密码。"
        >
          <input
            name="icloud_email"
            type="email"
            defaultValue={account?.icloud_email || ""}
            placeholder="name@icloud.com"
          />
        </Field>
        <Field
          label="App 专用密码"
          hint={
            account?.has_app_password
              ? "已配置；如需更换请填写新密码。"
              : "可稍后设置，不要填写 Apple ID 登录密码。"
          }
        >
          <input
            name="app_password"
            type="password"
            autoComplete="new-password"
            placeholder={
              account?.has_app_password
                ? "已配置 · 留空保留"
                : "xxxx-xxxx-xxxx-xxxx"
            }
          />
        </Field>
        <ErrorNotice error={error} />
        <div className="form-actions">
          {useApple && <Button type="button" variant="ghost" onClick={useApple} disabled={busy}>使用账号密码登录</Button>}
          {!account && (
            <a className="text-link" href="/api/cookie-helper/download">
              <Download size={14} />
              Cookie 助手
            </a>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={close}
          >
            取消
          </Button>
          <Submit busy={busy}>{account ? "保存设置" : "添加并校验"}</Submit>
        </div>
      </form>
    </Modal>
  );
}
export function Accounts({
  accounts,
  loading,
  refresh,
  add,
}: {
  accounts: Row[];
  loading: boolean;
  refresh: () => any;
  add: () => void;
}) {
  const [editing, setEditing] = useState<Row | null>(null);
  const [removing, setRemoving] = useState<Row | null>(null);
  const [login, setLogin] = useState<Row | null>(null);
  const [details, setDetails] = useState<Row | null>(null);
  const [benefits, setBenefits] = useState<Row | null>(null);
  const { enqueue } = useBackgroundTasks();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const errorOf = (a: Row) => a.error || a.last_error || a.last_mail_error;
  const statusOf = (a: Row) => a.status === "active" && (!a.has_cookies || errorOf(a)) ? "warning" : a.status;
  const healthy = accounts.filter((a) => statusOf(a) === "active").length;
  const search = query.trim().toLowerCase();
  const filtered = accounts.filter((a) =>
    (filter === "all" || (filter === "active" ? statusOf(a) === "active" : statusOf(a) !== "active")) &&
    [a.name, a.icloud_email, a.real_email].some((value) => String(value || "").toLowerCase().includes(search)),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * 10, currentPage * 10);
  return (
    <>
      <PageHead
        eyebrow="ACCOUNTS"
        title="账号管理"
        description="统一管理 iCloud 账号，保持邮箱与收件服务连接。"
      >
        <Button onClick={add}>
          <Plus />
          添加账号
        </Button>
      </PageHead>
      {loading ? (
        <Loading />
      ) : !accounts.length ? (
        <div className="panel">
          <Empty
            title="还没有连接账号"
            detail="添加第一个账号，开始创建和管理隐私邮箱。"
            action={
              <Button onClick={add}>
                <Plus />
                添加账号
              </Button>
            }
          />
        </div>
      ) : (
        <div className="panel accounts-panel">
          <div className="accounts-toolbar">
            <div className="accounts-filters" aria-label="账号状态筛选">
              {[["all", "全部账号", accounts.length], ["active", "正常", healthy], ["attention", "需处理", accounts.length - healthy]].map(([value, label, count]) => (
                <button key={value} aria-pressed={filter === value} className={filter === value ? "selected" : ""}
                  onClick={() => { setFilter(String(value)); setPage(1); }}>
                  {label}<span>{count}</span>
                </button>
              ))}
            </div>
            <SearchBox value={query} onChange={(value) => { setQuery(value); setPage(1); }} placeholder="搜索账号名称或邮箱…" />
          </div>
          {!filtered.length ? <Empty title="没有匹配的账号" detail="换个关键词，或查看全部账号。" action={<Button variant="outline" onClick={() => { setQuery(""); setFilter("all"); setPage(1); }}>清除筛选</Button>} /> : (
            <div className="table-wrap accounts-table-wrap">
              <table className="accounts-table" aria-label="iCloud 账号列表">
                <thead><tr><th scope="col">账号</th><th scope="col">状态</th><th scope="col">活跃 / 全部别名</th><th scope="col">连接配置</th><th scope="col">操作</th></tr></thead>
                <tbody>{visible.map((a) => (
                  <tr key={a.id}>
                    <td className="accounts-identity-cell">
                      <div className="accounts-identity">
                        <span className="accounts-avatar"><Cloud size={18} /></span>
                        <div><strong title={a.name}>{a.name || "iCloud 账号"}</strong><div className="accounts-address"><span title={a.icloud_email || a.real_email}>{a.icloud_email || a.real_email || "收件邮箱未设置"}</span><small>{a.host === "icloud.com.cn" ? "中国区" : "国际区"}</small></div></div>
                      </div>
                    </td>
                    <td className="accounts-status-cell"><Pill value={statusOf(a)} />{errorOf(a) && <button className="accounts-detail-link" aria-label={"查看连接详情 " + a.name} onClick={() => setDetails(a)}>查看详情</button>}</td>
                    <td className="accounts-count-cell" data-label="活跃 / 全部别名"><strong>{(a.alias_active || 0).toLocaleString()}</strong><span className="muted"> / {(a.alias_total || 0).toLocaleString()}</span></td>
                    <td className="accounts-connection-cell"><div><ShieldCheck size={14} />{a.has_cookies ? (a.login_method === "apple" ? "Apple 已连接" : "已导入 Cookie") : "需要登录"}</div><div><KeyRound size={14} />{a.has_app_password ? "收件已配置" : "收件待配置"}</div></td>
                    <td className="accounts-actions-cell"><div className="accounts-row-actions">
                      <Button variant="outline" size="sm" onClick={() => setLogin(a)}>重新登录</Button>
                      <Button variant="ghost" size="icon" aria-label={"家庭与方案 " + a.name} title="家庭与方案" onClick={() => setBenefits(a)}><Users /></Button>
                      <Button variant="ghost" size="icon" aria-label={"设置账号 " + a.name} title="账号设置" onClick={() => setEditing(a)}><Edit3 /></Button>
                      <Button variant="ghost" size="sm" onClick={() => enqueue("账号校验", [{ path: `/api/accounts/${enc(a.id)}/validate`, label: a.name || a.id }])}><CheckCircle2 />校验</Button>
                      <Button variant="ghost" size="icon" aria-label={"移除账号 " + a.name} title="移除账号" onClick={() => setRemoving(a)}><Trash2 /></Button>
                    </div></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          <Pager page={currentPage} pages={pages} total={filtered.length} onPage={setPage} />
        </div>
      )}
      <details className="panel accounts-help">
        <summary><span>家庭共享与 iCloud+<small>加入家庭、开通方案</small></span><ChevronDown size={16} /></summary>
        <div>
        <p className="muted">点击账号右侧的“家庭与方案”图标，可查看家庭成员、iCloud+ 来源和空间用量，并打开 Apple 邀请或方案页面。加入和付款需在 Apple 确认，完成后返回刷新状态。</p>
        <div className="form-actions">
          <a className="text-link" href="https://support.apple.com/zh-cn/108380" target="_blank" rel="noopener noreferrer">查看加入家庭步骤 ↗</a>
          <a className="text-link" href="https://support.apple.com/zh-cn/108349" target="_blank" rel="noopener noreferrer">查看 iCloud+ 付费开通步骤 ↗</a>
        </div>
        </div>
      </details>
      {benefits && <AccountBenefits key={benefits.id} account={benefits} close={() => setBenefits(null)} />}
      {details && <Modal title="账号连接详情" description={details.name || "iCloud 账号"} close={() => setDetails(null)}>
        <p className="muted">最近一次连接返回的信息：</p><pre className="accounts-error-detail">{String(errorOf(details))}</pre>
        <div className="form-actions"><Button variant="outline" onClick={() => setDetails(null)}>关闭</Button><Button onClick={() => { setLogin(details); setDetails(null); }}>重新登录</Button></div>
      </Modal>}
      {login && <AppleLoginForm account={login} close={() => setLogin(null)} done={() => { setLogin(null); refresh(); }} />}
      {editing && (
        <AccountForm
          account={editing}
          close={() => setEditing(null)}
          done={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}
      {removing && (
        <Confirm
          title="退出账号登录？"
          description={`将移除“${removing.name}”的登录状态并隐藏关联数据。`}
          close={() => setRemoving(null)}
          onConfirm={async () => {
            await post(`/api/accounts/${enc(removing.id)}/remove`);
            refresh();
            toast.success("账号已退出");
          }}
        />
      )}
    </>
  );
}
