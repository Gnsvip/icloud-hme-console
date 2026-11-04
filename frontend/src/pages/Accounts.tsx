import { useState } from "react";
import {
  CheckCircle2,
  Cloud,
  Download,
  Edit3,
  KeyRound,
  Plus,
  ShieldCheck,
  Trash2,
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
  Submit,
} from "@/components/common";
import { PageHead } from "@/components/PageHead";
import { AppleLoginForm } from "./AppleLogin";
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
  const [busy, setBusy] = useState("");
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
        <div className="account-card-grid">
          {accounts.map((a, i) => (
            <section className="panel account-detail-card" key={a.id}>
              <div className="account-card-top">
                <span className={"account-avatar color-" + (i % 4)}>
                  <Cloud size={22} />
                </span>
                <Pill value={a.status} />
              </div>
              <h2>{a.name || "iCloud 账号"}</h2>
              <p>{a.icloud_email || a.real_email || "收件邮箱未设置"}</p>
              <div className="account-card-numbers">
                <div>
                  <strong>{a.alias_total || 0}</strong>
                  <small>全部别名</small>
                </div>
                <div>
                  <strong>{a.alias_active || 0}</strong>
                  <small>活跃别名</small>
                </div>
              </div>
              <div className="account-check">
                <ShieldCheck size={15} />
                {a.has_cookies ? (a.login_method === "apple" ? "Apple 已连接" : "已导入 Cookie") : "需要登录"}
                <span />
                <KeyRound size={15} />
                {a.has_app_password ? "收件已配置" : "收件待配置"}
              </div>
              {(a.error || a.last_error || a.last_mail_error) && (
                <div className="account-warning">
                  {a.error || a.last_error || a.last_mail_error}
                </div>
              )}
              <div className="account-card-actions">
                <Button variant="outline" size="sm" onClick={() => setLogin(a)}>重新登录</Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditing(a)}
                >
                  <Edit3 />
                  设置
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy === a.id}
                  onClick={async () => {
                    setBusy(a.id);
                    try {
                      await post(`/api/accounts/${enc(a.id)}/validate`);
                      toast.success("账号校验完成");
                      refresh();
                    } catch (err) {
                      toast.error(err.message);
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  <CheckCircle2 />
                  {busy === a.id ? "校验中…" : "校验"}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={"移除账号 " + a.name}
                  onClick={() => setRemoving(a)}
                >
                  <Trash2 />
                </Button>
              </div>
            </section>
          ))}
        </div>
      )}
      <section className="panel" style={{ padding: 24, marginTop: 20 }}>
        <h2>家庭共享与 iCloud+</h2>
        <p className="muted">加入已共享 iCloud+ 的家庭后，可以使用隐藏邮件地址。接受家庭邀请或购买方案需要在 Apple 的官方流程中确认，完成后返回这里校验账号。</p>
        <div className="form-actions">
          <a className="text-link" href="https://support.apple.com/zh-cn/108380" target="_blank" rel="noopener noreferrer">查看加入家庭步骤 ↗</a>
          <a className="text-link" href="https://support.apple.com/zh-cn/108349" target="_blank" rel="noopener noreferrer">查看 iCloud+ 付费开通步骤 ↗</a>
        </div>
      </section>
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
