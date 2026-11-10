import { useBackgroundTasks } from "@/components/BackgroundTasks";
import { useEffect, useState } from "react";
import {
  Download,
  ExternalLink,
  Link2,
  Mail,
  Play,
  Plus,
  Save,
  Settings2,
  Square,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  api,
  download,
  enc,
  post,
  stamp,
  useDebounced,
  useRemote,
  type Row,
} from "@/lib/api";
import {
  Button,
  Confirm,
  CopyButton,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Modal,
  Pager,
  Pill,
  RefreshButton,
  SearchBox,
  Submit,
} from "@/components/common";
import { PageHead } from "@/components/PageHead";

function AccountChecks({
  accounts,
  value,
  onChange,
}: {
  accounts: Row[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="account-choices">
      {accounts.map((a) => (
        <label key={a.id}>
          <input
            type="checkbox"
            checked={value.includes(a.id)}
            onChange={(e) =>
              onChange(
                e.target.checked
                  ? [...value, a.id]
                  : value.filter((id) => id !== a.id),
              )
            }
          />
          <span>
            <strong>{a.name}</strong>
            <small>{a.icloud_email || a.real_email || a.id}</small>
          </span>
          <Pill value={a.status} />
        </label>
      ))}
      {!accounts.length && <p className="muted">请先添加 iCloud 账号。</p>}
    </div>
  );
}
export function Batch({
  accounts,
  state,
  refresh,
}: {
  accounts: Row[];
  state: Row;
  refresh: () => any;
}) {
  const [selected, setSelected] = useState<string[]>([]),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(null);
  const { enqueue } = useBackgroundTasks();
  const stock = useRemote("/api/auto-stock");
  const [config, setConfig] = useState<Row | null>(null);
  useEffect(() => {
    if (stock.data && !config) setConfig(stock.data.config);
  }, [stock.data, config]);
  async function run(name: string, fn: () => Promise<any>) {
    setBusy(name);
    setError(null);
    try {
      const d = await fn();
      toast.success(d.message || "操作成功");
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <PageHead
        eyebrow="AUTOMATION"
        title="把重复工作，交给自动化。"
        description="批量创建隐私地址，或让工作台自动补充可用库存。"
      />
      <ErrorNotice error={error || stock.error} retry={stock.refetch} />
      <div className="tools-grid">
        <section className="panel form-panel">
          <div className="section-head">
            <div>
              <h2>批量创建</h2>
              <p>选择账号，按需创建邮箱</p>
            </div>
            <Plus size={19} />
          </div>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              run("batch", () =>
                post("/api/create-batch", {
                  account_ids: selected,
                  count_per_account: Number(f.get("count")),
                  label: f.get("label"),
                  create_pickup_links: f.has("links"),
                }),
              );
            }}
          >
            <AccountChecks
              accounts={accounts}
              value={selected}
              onChange={setSelected}
            />
            <div className="form-grid">
              <Field label="每个账号创建数量">
                <input
                  name="count"
                  type="number"
                  min="1"
                  max="20"
                  defaultValue="5"
                  required
                />
              </Field>
              <Field label="邮箱标签">
                <input name="label" placeholder="例如：注册备用" />
              </Field>
            </div>
            <label className="check-label">
              <input type="checkbox" name="links" />
              同时生成取码链接
            </label>
            <Submit busy={!!busy || !!state.creating} disabled={!selected.length}>
              <Play />
              开始创建
            </Submit>
            {state.creating && (
              <div className="info-box">
                {state.round_status || "创建任务正在后台运行…"} · 已创建{" "}
                {state.current_round_created || 0} 个
              </div>
            )}
            {state.last_error && (
              <div className="error-notice">{state.last_error}</div>
            )}
          </form>
        </section>
        <section className="panel form-panel">
          <div className="section-head">
            <div>
              <h2>自动调度</h2>
              <p>按既有调度规则持续运行</p>
            </div>
            <Settings2 size={19} />
          </div>
          <div className="scheduler-status">
            <span
              className={"status-dot " + (!state.running ? "offline" : "")}
            />
            <strong>{state.running ? "调度器正在运行" : "调度器已暂停"}</strong>
            <small>下次执行：{stamp(state.next_trigger)}</small>
          </div>
          <p className="section-description">
            北京时间 07:00–20:00 执行，自动补货优先。各轮间隔由调度器安排。
          </p>
          <Button
            variant={state.running ? "outline" : "default"}
            disabled={!!busy}
            onClick={() =>
              run("scheduler", () =>
                post("/api/scheduler/" + (state.running ? "stop" : "start")),
              )
            }
          >
            {state.running ? <Square /> : <Play />}
            {state.running ? "停止调度" : "启动调度"}
          </Button>
        </section>
      </div>
      <section className="panel form-panel stock-panel">
        <div className="section-head">
          <div>
            <h2>自动补货规则</h2>
            <p>按现有服务规则，每轮创建指定数量，并分批分配到所选账号</p>
          </div>
        </div>
        {!config ? (
          <Loading />
        ) : (
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              run("stock", () => post("/api/auto-stock", config));
            }}
          >
            <div className="stock-options">
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={!!config.enabled}
                  onChange={(e) =>
                    setConfig({ ...config, enabled: e.target.checked })
                  }
                />
                启用自动补货
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={!!config.all_accounts}
                  onChange={(e) =>
                    setConfig({ ...config, all_accounts: e.target.checked })
                  }
                />
                应用于全部账号
              </label>
            </div>
            {!config.all_accounts && (
              <AccountChecks
                accounts={accounts}
                value={config.account_ids || []}
                onChange={(v) => setConfig({ ...config, account_ids: v })}
              />
            )}
            <div className="form-grid thirds">
              <Field label="标签前缀">
                <input
                  value={config.prefix || ""}
                  onChange={(e) =>
                    setConfig({ ...config, prefix: e.target.value })
                  }
                />
              </Field>
              <Field label="每轮创建总数">
                <input
                  type="number"
                  min="0"
                  max="10000"
                  required
                  value={config.target ?? 0}
                  onChange={(e) =>
                    setConfig({ ...config, target: Number(e.target.value) })
                  }
                />
              </Field>
              <Field label="单轮创建数量">
                <input
                  type="number"
                  min="1"
                  max="5"
                  required
                  value={config.batch || 1}
                  onChange={(e) =>
                    setConfig({ ...config, batch: Number(e.target.value) })
                  }
                />
              </Field>
            </div>
            <div className="form-actions">
              <Button
                type="button"
                variant="outline"
                disabled={!!busy || state.creating}
                onClick={() =>
                  enqueue("立即补货", [{ path: "/api/auto-stock/run", body: config }])
                }
              >
                <Play />
                立即补货一次
              </Button>
              <Submit busy={!!busy}>
                <Save />
                保存规则
              </Submit>
            </div>
          </form>
        )}
      </section>
    </>
  );
}
function absoluteLink(url: string) {
  return new URL(url, location.origin).href;
}
export function LinkGenerator({
  initial = "",
  close,
}: {
  initial?: string;
  close: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(null),
    [result, setResult] = useState<Row | null>(null);
  const text = (result?.results || [])
    .map(
      (r: Row) => `${r.lookup_email || r.email}\t${absoluteLink(r.pickup_url)}`,
    )
    .join("\n");
  return (
    <Modal
      title="生成取码链接"
      description="每行一个邮箱地址。链接持有者可读取对应邮箱的验证码，请妥善分享。"
      close={() => !busy && close()}
      wide
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          setError(null);
          try {
            setResult(
              await post(
                "/api/pickup-links/batch",
                {
                  emails: f.get("emails"),
                  per_email: Number(f.get("per_email")),
                  random_tags: Number(f.get("per_email")) > 0,
                },
                300000,
              ),
            );
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="邮箱地址">
          <textarea
            name="emails"
            rows={5}
            defaultValue={initial}
            required
            placeholder="example@icloud.com"
          />
        </Field>
        <Field
          label="每个邮箱的随机标签链接数"
          hint="填 0 时为原始邮箱生成链接；1–100 会生成随机标签地址。"
        >
          <input
            name="per_email"
            type="number"
            min="0"
            max="100"
            defaultValue="0"
            required
          />
        </Field>
        <ErrorNotice error={error} />
        <div className="form-actions">
          <Submit busy={busy}>
            <Link2 />
            生成链接
          </Submit>
        </div>
      </form>
      {result && (
        <div className="result-box">
          <strong>
            已生成 {result.count || result.results?.length || 0} 条链接
          </strong>
          {result.errors?.length > 0 && (
            <div className="error-notice">
              {result.errors
                .map((r: Row) => `${r.email}: ${r.error}`)
                .join("；")}
            </div>
          )}
          <textarea aria-label="生成的链接" readOnly value={text} rows={5} />
          <div className="form-actions">
            <CopyButton value={text} label="复制结果" />
            <Button
              variant="outline"
              onClick={() => download(text, "取码链接.txt")}
            >
              <Download />
              导出
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
export function PickupLinks() {
  const { enqueue } = useBackgroundTasks();
  const [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [size, setSize] = useState(20),
    [selected, setSelected] = useState<Record<string, Row>>({}),
    [create, setCreate] = useState(false),
    [revoke, setRevoke] = useState<Row[] | null>(null);
  const q = useDebounced(search),
    query = useRemote(
      `/api/pickup-links?page=${page}&page_size=${size}&q=${enc(q)}`,
    );
  useEffect(() => setPage(1), [q, size]);
  const rows: Row[] = query.data?.records || [];
  const chosen = Object.values(selected);
  const linkText = (items: Row[]) =>
    items.map((r) => `${r.email}\t${absoluteLink(r.pickup_url)}`).join("\n");
  return (
    <>
      <PageHead
        eyebrow="PICKUP LINKS"
        title="一个链接，直达验证码。"
        description="查找和管理独立取码链接，随时撤销不再使用的访问入口。"
      >
        <RefreshButton
          busy={query.isFetching}
          onClick={() => query.refetch()}
        />
        <Button onClick={() => setCreate(true)}>
          <Plus />
          生成链接
        </Button>
      </PageHead>
      <section className="panel">
        <div className="table-toolbar">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="搜索邮箱或链接编号…"
          />
          <div className="toolbar-spacer" />
          <Button
            variant="outline"
            size="sm"
            disabled={!rows.length}
            onClick={() => download(linkText(rows), "取码链接-当前页.txt")}
          >
            <Download />
            导出本页
          </Button>
        </div>
        {chosen.length > 0 && (
          <div className="selection-bar">
            <span>{chosen.length} 项已选择</span>
            <CopyButton value={linkText(chosen)} label="复制链接" />
            <Button size="sm" variant="ghost" onClick={() => setRevoke(chosen)}>
              <Trash2 />
              撤销访问
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected({})}>
              取消选择
            </Button>
          </div>
        )}
        <ErrorNotice error={query.error} retry={query.refetch} />
        {query.isPending ? (
          <Loading />
        ) : !rows.length ? (
          <Empty
            title="没有取码链接"
            detail="从邮箱列表选择地址，或点击右上角生成链接。"
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="check-cell">
                    <input
                      type="checkbox"
                      aria-label="选择本页链接"
                      disabled={query.isPlaceholderData}
                      checked={rows.every((r) => selected[r.id])}
                      onChange={(e) => {
                        const on = e.target.checked;
                        setSelected((old) => {
                          const n = { ...old };
                          rows.forEach((r) => {
                            if (on) n[r.id] = r;
                            else delete n[r.id];
                          });
                          return n;
                        });
                      }}
                    />
                  </th>
                  <th>邮箱地址</th>
                  <th>链接编号</th>
                  <th>生成时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={"选择链接 " + r.id}
                        disabled={query.isPlaceholderData}
                        checked={!!selected[r.id]}
                        onChange={() =>
                          setSelected((old) => {
                            const n = { ...old };
                            if (n[r.id]) delete n[r.id];
                            else n[r.id] = r;
                            return n;
                          })
                        }
                      />
                    </td>
                    <td>
                      <span className="email-cell">
                        <Link2 size={15} />
                        {r.email}
                      </span>
                    </td>
                    <td className="muted">#{r.id}</td>
                    <td className="muted">{stamp(r.created_at)}</td>
                    <td>
                      <div className="inline-actions">
                        <CopyButton
                          value={absoluteLink(r.pickup_url)}
                          label="复制"
                        />
                        <a
                          className="icon-link"
                          aria-label={"打开链接 " + r.id}
                          href={r.pickup_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <ExternalLink size={15} />
                        </a>
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={"撤销链接 " + r.id}
                          disabled={query.isPlaceholderData}
                          onClick={() => setRevoke([r])}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager
          page={query.data?.page || page}
          pages={query.data?.pages || 1}
          total={query.data?.total || 0}
          size={size}
          onSize={setSize}
          onPage={setPage}
        />
      </section>
      {create && (
        <LinkGenerator
          close={() => {
            setCreate(false);
            query.refetch();
          }}
        />
      )}
      {revoke && (
        <Confirm
          title={`撤销 ${revoke.length} 个链接？`}
          description="撤销后，原链接将无法继续读取验证码。邮箱本身不受影响。"
          close={() => setRevoke(null)}
          onConfirm={async () => {
            enqueue("撤销取码链接", [{ path: "/api/pickup-links/revoke-batch", body: { link_ids: revoke.map(r => r.id) } }]);
            setSelected({});
          }}
        />
      )}
    </>
  );
}
export function ForwardSettings({ accounts }: { accounts: Row[] }) {
  const query = useRemote("/api/forward-config"),
    [edit, setEdit] = useState<Row | null>(null),
    [remove, setRemove] = useState<Row | null>(null);
  const rows: Row[] = query.data?.configs || [];
  return (
    <>
      <PageHead
        eyebrow="FORWARDING"
        title="连接你的转发邮箱。"
        description="为 iCloud 账号绑定 QQ 或 Microsoft 邮箱，补充验证码收取渠道。"
      >
        <Button
          onClick={() =>
            setEdit({ enabled: true, provider: "qq", mailbox: "INBOX" })
          }
        >
          <Plus />
          新增绑定
        </Button>
      </PageHead>
      <ErrorNotice error={query.error} retry={query.refetch} />
      {query.isPending ? (
        <Loading />
      ) : !rows.length ? (
        <section className="panel">
          <Empty
            title="还没有转发邮箱"
            detail="添加一个绑定，从转发邮箱读取验证码。"
            action={
              <Button
                onClick={() =>
                  setEdit({ enabled: true, provider: "qq", mailbox: "INBOX" })
                }
              >
                <Plus />
                新增绑定
              </Button>
            }
          />
        </section>
      ) : (
        <div className="account-card-grid">
          {rows.map((r) => (
            <section className="panel forward-card" key={r.id}>
              <div className="account-card-top">
                <span className="account-avatar color-1">
                  <Mail size={22} />
                </span>
                <Pill value={r.enabled ? "active" : "disabled"} />
              </div>
              <h2>
                {r.provider === "microsoft" ? "Microsoft / Outlook" : "QQ 邮箱"}
              </h2>
              <p>{r.username}</p>
              <div className="binding-info">
                绑定至{" "}
                <strong>
                  {accounts.find((a) => a.id === r.account_id)?.name ||
                    r.account_id}
                </strong>
                <small>
                  {r.provider === "microsoft"
                    ? r.has_refresh_token
                      ? "OAuth2 已授权"
                      : "等待 OAuth2 授权"
                    : r.has_password
                      ? "IMAP 授权码已配置"
                      : "等待填写授权码"}
                </small>
              </div>
              <div className="account-card-actions">
                <Button size="sm" variant="outline" onClick={() => setEdit(r)}>
                  <Settings2 />
                  编辑配置
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={"删除绑定 " + r.username}
                  onClick={() => setRemove(r)}
                >
                  <Trash2 />
                </Button>
              </div>
            </section>
          ))}
        </div>
      )}
      {edit && (
        <ForwardEditor
          accounts={accounts}
          profile={edit}
          close={() => {
            setEdit(null);
            query.refetch();
          }}
        />
      )}
      {remove && (
        <Confirm
          title="删除转发邮箱绑定？"
          description={remove.username + " 将不再用于收取验证码。"}
          close={() => setRemove(null)}
          onConfirm={async () => {
            await api("/api/forward-config/" + enc(remove.id), {
              method: "DELETE",
            });
            query.refetch();
          }}
        />
      )}
    </>
  );
}
function ForwardEditor({
  accounts,
  profile,
  close,
}: {
  accounts: Row[];
  profile: Row;
  close: () => void;
}) {
  const [provider, setProvider] = useState(profile.provider || "qq"),
    [saved, setSaved] = useState(profile),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(null),
    [auth, setAuth] = useState<Row | null>(null);
  useEffect(() => {
    if (!auth) return;
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const d = await post(
          `/api/forward-config/${enc(saved.id)}/microsoft/poll`,
          { device_code: auth.device_code },
        );
        if (stopped) return;
        if (d.authorized) {
          setAuth(null);
          setSaved({ ...saved, has_refresh_token: true });
          toast.success("Microsoft 授权成功");
          return;
        }
        timer = setTimeout(poll, Math.max(5, auth.interval || 5) * 1000);
      } catch (e) {
        if (!stopped) {
          setError(e);
          setAuth(null);
        }
      }
    };
    timer = setTimeout(poll, Math.max(5, auth.interval || 5) * 1000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [auth, saved.id]);
  return (
    <Modal
      title="转发邮箱配置"
      description="密码和授权码留空将保留现有值。"
      close={() => !busy && close()}
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          setError(null);
          setAuth(null);
          try {
            const d = await post("/api/forward-config", {
              ...Object.fromEntries(f),
              id: saved.id,
              enabled: f.has("enabled"),
              test:
                f.has("enabled") &&
                (provider === "qq" || !!saved.has_refresh_token),
            });
            setSaved(d.config);
            toast.success(d.test ? "配置已保存，连接测试成功" : "配置已保存");
            if (provider === "microsoft" && !d.config.has_refresh_token)
              setAuth(
                await post(
                  `/api/forward-config/${enc(d.config.id)}/microsoft/start`,
                ),
              );
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="form-grid">
          <Field label="绑定 iCloud 账号">
            <select
              name="account_id"
              defaultValue={profile.account_id || ""}
              required
            >
              <option value="">选择账号</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="邮箱服务">
            <select
              name="provider"
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
                setAuth(null);
              }}
            >
              <option value="qq">QQ 邮箱</option>
              <option value="microsoft">Microsoft / Outlook</option>
            </select>
          </Field>
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            name="enabled"
            defaultChecked={profile.enabled}
          />
          启用这条绑定
        </label>
        <Field label="收件邮箱">
          <input
            type="email"
            name="username"
            defaultValue={profile.username || ""}
            required
          />
        </Field>
        {provider === "qq" ? (
          <Field label="IMAP 授权码">
            <input
              type="password"
              autoComplete="new-password"
              name="password"
              placeholder={
                saved.has_password
                  ? "已配置 · 留空保留"
                  : "填写 QQ 邮箱 IMAP 授权码"
              }
            />
          </Field>
        ) : (
          <div className="form-grid">
            <Field label="应用客户端 ID">
              <input
                name="client_id"
                defaultValue={profile.client_id || ""}
                required
              />
            </Field>
            <Field label="租户">
              <input
                name="tenant"
                defaultValue={profile.tenant || "consumers"}
                required
              />
            </Field>
          </div>
        )}
        <Field label="扫描文件夹">
          <input
            name="mailbox"
            defaultValue={profile.mailbox || "INBOX"}
            required
          />
        </Field>
        <div className="info-box">
          {provider === "qq" ? "imap.qq.com" : "outlook.office365.com"} · 993 /
          SSL
        </div>
        <ErrorNotice error={error} />
        {auth && (
          <div className="oauth-box">
            <span>在 Microsoft 页面输入以下授权码</span>
            <strong>{auth.user_code}</strong>
            <CopyButton value={auth.user_code} label="复制授权码" />
            <a
              href={auth.verification_uri_complete || auth.verification_uri}
              target="_blank"
              rel="noopener noreferrer"
            >
              打开 Microsoft 授权
              <ExternalLink size={14} />
            </a>
            <small>等待你完成授权…</small>
          </div>
        )}
        <div className="form-actions">
          <Button
            variant="outline"
            type="button"
            onClick={close}
            disabled={busy}
          >
            关闭
          </Button>
          <Submit busy={busy}>
            {provider === "microsoft" && !saved.has_refresh_token
              ? "保存并开始授权"
              : "保存并测试"}
          </Submit>
        </div>
      </form>
    </Modal>
  );
}
export function Logs() {
  const { enqueue } = useBackgroundTasks();
  const query = useRemote("/api/logs?limit=500", true, 10000),
    [level, setLevel] = useState("all"),
    [search, setSearch] = useState(""),
    [cleanup, setCleanup] = useState(false);
  const rows: Row[] = (query.data?.logs || []).filter(
    (r: Row) =>
      (level === "all" || r.level === level) &&
      (!search || r.msg.toLowerCase().includes(search.toLowerCase())),
  );
  return (
    <>
      <PageHead
        eyebrow="ACTIVITY"
        title="运行日志"
        description="查看最近 500 条运行记录，快速定位任务与连接问题。"
      >
        <RefreshButton
          busy={query.isFetching}
          onClick={() => query.refetch()}
        />
        <Button variant="outline" onClick={() => setCleanup(true)}>
          <Trash2 />
          清理旧日志
        </Button>
      </PageHead>
      <section className="panel">
        <div className="table-toolbar">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="搜索日志内容…"
          />
          <select
            aria-label="日志级别"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          >
            <option value="all">全部级别</option>
            <option value="info">信息</option>
            <option value="success">成功</option>
            <option value="warn">警告</option>
            <option value="error">错误</option>
          </select>
          <div className="toolbar-spacer" />
          <span className="muted">{rows.length} 条记录 · 自动更新</span>
        </div>
        <ErrorNotice error={query.error} retry={query.refetch} />
        {query.isPending ? (
          <Loading />
        ) : !rows.length ? (
          <Empty title="暂无匹配日志" />
        ) : (
          <div className="log-list">
            {[...rows].reverse().map((r, i) => (
              <div className="log-row" key={i}>
                <time>{r.time}</time>
                <span className={"log-level " + r.level}>
                  {(
                    {
                      info: "信息",
                      success: "成功",
                      warn: "警告",
                      error: "错误",
                    } as Row
                  )[r.level] || r.level}
                </span>
                <p>{r.msg}</p>
              </div>
            ))}
          </div>
        )}
      </section>
      {cleanup && (
        <Confirm
          title="清理 14 天前的日志？"
          description="将保留最近 14 天的运行记录，更早的记录会永久删除。"
          close={() => setCleanup(false)}
          onConfirm={async () => {
            enqueue("清理历史日志", [{ path: "/api/logs/cleanup", body: { days: 14 } }]);
          }}
        />
      )}
    </>
  );
}
