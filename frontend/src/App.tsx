import { lazy, Suspense, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Boxes,
  ChevronRight,
  Cloud,
  Command,
  LayoutDashboard,
  Link2,
  LogOut,
  Mail,
  Menu,
  Moon,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sun,
  Terminal,
  Users,
} from "lucide-react";
import { post, stamp, useRemote, type Row } from "./lib/api";
import { PageHead } from "./components/PageHead";
import { PageBoundary } from "./components/PageBoundary";
const AccountForm = lazy(() => import("./pages/Accounts").then(m => ({ default: m.AccountForm })));
const Accounts = lazy(() => import("./pages/Accounts").then(m => ({ default: m.Accounts })));
const Mailboxes = lazy(() => import("./pages/Mailboxes").then(m => ({ default: m.Mailboxes })));
const InboxPage = lazy(() => import("./pages/Inbox").then(m => ({ default: m.InboxPage })));
const Batch = lazy(() => import("./pages/Tools").then(m => ({ default: m.Batch })));
const ForwardSettings = lazy(() => import("./pages/Tools").then(m => ({ default: m.ForwardSettings })));
const Logs = lazy(() => import("./pages/Tools").then(m => ({ default: m.Logs })));
const PickupLinks = lazy(() => import("./pages/Tools").then(m => ({ default: m.PickupLinks })));
import {
  Button,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Modal,
  Pill,
  Submit,
} from "./components/common";
const navigation = [
  ["dashboard", "工作概览", LayoutDashboard],
  ["emails", "隐私邮箱", Mail],
  ["codes", "收码台", Boxes],
  ["inbox", "收件箱", Mail],
  ["accounts", "账号管理", Users],
  ["batch", "批量创建", Plus],
  ["links", "取码链接", Link2],
  ["settings", "转发设置", Settings2],
  ["logs", "运行日志", Terminal],
  ["docs", "API 文档", BookOpen],
] as const;
function currentTab() {
  const name = location.hash.slice(1).split("?")[0];
  return navigation.some((n) => n[0] === name) ? name : "dashboard";
}
export default function App() {
  const client = useQueryClient();
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [tab, setTab] = useState(currentTab);
  const [mobile, setMobile] = useState(false);
  const [add, setAdd] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("hme-theme") || "light",
  );
  const [command, setCommand] = useState(false);
  const [search, setSearch] = useState("");
  useEffect(() => {
    fetch("/api/admin/session", { credentials: "same-origin" })
      .then((r) => r.json())
      .then((d) => setAuthenticated(!!d.ok))
      .catch(() => setAuthenticated(false));
    const expired = () => {
      setAuthenticated(false);
      client.clear();
    };
    window.addEventListener("hme-session-expired", expired);
    return () => window.removeEventListener("hme-session-expired", expired);
  }, [client]);
  useEffect(() => {
    const update = () => {
      setTab(currentTab());
      setMobile(false);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("hme-theme", theme);
  }, [theme]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCommand((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const accountsQuery = useRemote(
    "/api/accounts",
    authenticated === true,
    30000,
  );
  const stateQuery = useRemote("/api/state", authenticated === true, 15000);
  const accounts: Row[] = accountsQuery.data?.accounts || [];
  const state = stateQuery.data || {};
  const refresh = () =>
    client.invalidateQueries({
      predicate: (q) => q.queryKey[0] !== "/api/admin/session",
    });
  const go = (name: string) => {
    location.hash = name;
    setCommand(false);
  };
  if (authenticated === null)
    return (
      <div className="boot">
        <Cloud size={36} />
        <span>正在连接工作台…</span>
      </div>
    );
  if (!authenticated) return <Login onLogin={() => setAuthenticated(true)} />;
  return (
    <div className="app-shell">
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="关闭导航"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={"app-sidebar " + (mobile ? "is-open" : "")}>
        <a href="#dashboard" className="brand">
          <span className="brand-icon">
            <Cloud size={22} />
          </span>
          <span>
            iCloud HME<small>隐私邮箱工作台</small>
          </span>
          <ChevronRight size={14} />
        </a>
        <button className="workspace-switch" onClick={() => go("accounts")}>
          <span className="workspace-icon">H</span>
          <span>
            我的工作空间<small>{accounts.length} 个 iCloud 账号</small>
          </span>
          <Settings2 size={14} />
        </button>
        <div className="nav-label">工作空间</div>
        <nav aria-label="主导航">
          {navigation.slice(0, 4).map(([id, label, Icon]) => (
            <a
              href={"#" + id}
              aria-current={tab === id ? "page" : undefined}
              className={tab === id ? "active" : ""}
              key={id}
            >
              <Icon size={17} />
              <span>{label}</span>
              {id === "emails" && state.total_aliases > 0 && (
                <b>{state.total_aliases.toLocaleString()}</b>
              )}
            </a>
          ))}
        </nav>
        <div className="nav-label">管理与工具</div>
        <nav aria-label="管理导航">
          {navigation.slice(4).map(([id, label, Icon]) => (
            <a
              href={"#" + id}
              aria-current={tab === id ? "page" : undefined}
              className={tab === id ? "active" : ""}
              key={id}
            >
              <Icon size={17} />
              <span>{label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="service-note">
            <span className="status-dot" />
            <div>
              {state.creating
                ? "正在创建邮箱"
                : state.running
                  ? "自动调度运行中"
                  : "工作台已连接"}
              <small>
                {state.creating
                  ? state.round_status
                  : "北京时间 · Asia / Shanghai"}
              </small>
            </div>
          </div>
          <button
            className="profile"
            onClick={async () => {
              await post("/api/admin/logout");
              client.clear();
              setAuthenticated(false);
            }}
          >
            <span className="avatar">A</span>
            <span>
              管理员<small>退出当前登录</small>
            </span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <Button
            variant="ghost"
            size="icon"
            className="mobile-menu"
            aria-label="打开导航"
            onClick={() => setMobile(true)}
          >
            <Menu />
          </Button>
          <div className="breadcrumb">
            工作空间
            <ChevronRight size={13} />
            <strong>{navigation.find((n) => n[0] === tab)?.[1]}</strong>
          </div>
          <div className="topbar-actions">
            {state.demo && (
              <span className="preview-badge">模拟数据 · 本地预览</span>
            )}
            <button
              className="command-button"
              aria-label="搜索工作台"
              onClick={() => setCommand(true)}
            >
              <Search size={15} />
              <span>搜索工作台…</span>
              <kbd>⌘ K</kbd>
            </button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={theme === "light" ? "切换深色" : "切换浅色"}
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              {theme === "light" ? <Moon /> : <Sun />}
            </Button>
            <span className="topbar-separator" />
            <span className="avatar small">A</span>
          </div>
        </header>
        <main
          id="main-content"
          className={"page-content " + (tab === "inbox" ? "mail-content" : "")}
        >
          <ErrorNotice
            error={accountsQuery.error || stateQuery.error}
            retry={refresh}
          />
          <PageBoundary key={tab}><Suspense fallback={<Loading />} >
          {tab === "dashboard" && (
            <Dashboard
              accounts={accounts}
              state={state}
              go={go}
              add={() => setAdd(true)}
            />
          )}
          {tab === "accounts" && (
            <Accounts
              accounts={accounts}
              loading={accountsQuery.isPending}
              refresh={refresh}
              add={() => setAdd(true)}
            />
          )}
          {(tab === "emails" || tab === "codes") && (
            <Mailboxes key={tab} mode={tab} accounts={accounts} />
          )}
          {tab === "inbox" && <InboxPage accounts={accounts} />}
          {tab === "batch" && (
            <Batch accounts={accounts} state={state} refresh={refresh} />
          )}
          {tab === "links" && <PickupLinks />}
          {tab === "settings" && <ForwardSettings accounts={accounts} />}
          {tab === "logs" && <Logs />}
          {tab === "docs" && <Docs />}
          </Suspense></PageBoundary>
        </main>
        <footer className="app-footer">
          <span>
            iCloud HME <i /> 让每个邮箱，井然有序。
          </span>
          <span>所有时间均为北京时间</span>
        </footer>
      </div>
      {add && (
        <PageBoundary><Suspense fallback={<Loading />}><AccountForm
          close={() => setAdd(false)}
          done={() => {
            setAdd(false);
            refresh();
          }}
        /></Suspense></PageBoundary>
      )}
      {command && (
        <Modal
          title="搜索工作台"
          description="跳转到功能，或输入邮箱地址搜索。"
          close={() => setCommand(false)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              go("emails?search=" + encodeURIComponent(search));
            }}
          >
            <div className="search-field command-input">
              <Search size={18} />
              <input
                autoFocus
                placeholder="输入页面名称或邮箱地址"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <kbd>↵</kbd>
            </div>
          </form>
          <div className="command-results">
            {navigation
              .filter(
                (n) =>
                  !search ||
                  n[1].includes(search) ||
                  n[0].includes(search.toLowerCase()),
              )
              .map(([id, label, Icon]) => (
                <button key={id} onClick={() => go(id)}>
                  <Icon size={17} />
                  {label}
                  <ArrowUpRight size={14} />
                </button>
              ))}
            {search && (
              <button
                onClick={() =>
                  go("emails?search=" + encodeURIComponent(search))
                }
              >
                <Search size={17} />
                在邮箱中搜索“{search}”<ArrowRight size={14} />
              </button>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
function Dashboard({
  accounts,
  state,
  go,
  add,
}: {
  accounts: Row[];
  state: Row;
  go: (s: string) => void;
  add: () => void;
}) {
  const query = useRemote(
    "/api/inventory?group=all&page=1&page_size=5",
    true,
    30000,
  );
  const summary = query.data?.summary || {};
  return (
    <>
      <PageHead
        eyebrow="YOUR WORKSPACE"
        title="邮箱工作，一目了然。"
        description="管理你的隐私邮箱、查看新邮件，让重要验证码随时可用。"
      >
        <Button variant="outline" onClick={() => go("inbox")}>
          <Mail />
          查看收件箱
        </Button>
        <Button onClick={add}>
          <Plus />
          添加账号
        </Button>
      </PageHead>
      <ErrorNotice error={query.error} retry={query.refetch} />
      <div className="stat-grid">
        {[
          ["隐私邮箱", state.total_aliases, Mail, "已关联的邮箱别名"],
          ["可用库存", summary.unused, Boxes, "等待使用的隐私地址"],
          [
            "活跃账号",
            state.active_accounts,
            ShieldCheck,
            `共 ${accounts.length} 个已添加账号`,
          ],
          ["今日创建", state.today_created, Plus, "今天新建的邮箱地址"],
        ].map(([label, value, Icon, detail]: any) => (
          <div className="stat-card" key={label}>
            <div>
              {label}
              <Icon size={18} />
            </div>
            <strong>
              {value == null ? "—" : Number(value).toLocaleString()}
            </strong>
            <small>{detail}</small>
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="section-head">
            <div>
              <h2>账号状态</h2>
              <p>各账号的连接状态与别名数量</p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => go("accounts")}>
              管理账号
              <ArrowUpRight />
            </Button>
          </div>
          {!accounts.length ? (
            <Empty
              title="添加你的第一个账号"
              detail="导入 iCloud Cookie 后，即可统一管理隐私邮箱。"
              action={
                <Button onClick={add}>
                  <Plus />
                  添加账号
                </Button>
              }
            />
          ) : (
            <div className="account-overview">
              {accounts.map((a, i) => (
                <button
                  key={a.id}
                  onClick={() => go("accounts")}
                  className="account-overview-row"
                >
                  <span className={"account-avatar color-" + (i % 4)}>
                    {(a.name || "iC").slice(0, 1)}
                  </span>
                  <span className="account-info">
                    <strong>{a.name || "iCloud 账号"}</strong>
                    <small>
                      {a.icloud_email || a.real_email || "尚未设置收件邮箱"}
                    </small>
                  </span>
                  <Pill value={a.status} />
                  <span className="account-number">
                    {a.alias_total || 0}
                    <small>个别名</small>
                  </span>
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>
          )}
        </section>
        <section className="panel workflow-panel">
          <div className="section-head">
            <div>
              <h2>开始下一项工作</h2>
              <p>常用操作，触手可及</p>
            </div>
            <Command size={18} />
          </div>
          {[
            ["emails", "整理邮箱", "查找地址、编辑标签与导出邮箱", Mail],
            ["codes", "查看验证码", "按状态筛选，快速复制最新验证码", Boxes],
            ["batch", "批量创建", "设置创建任务与自动补货", Plus],
            ["links", "生成取码链接", "为指定邮箱创建独立取码页面", Link2],
          ].map(([id, title, desc, Icon]: any) => (
            <button className="workflow-item" key={id} onClick={() => go(id)}>
              <span>
                <Icon size={18} />
              </span>
              <div>
                <strong>{title}</strong>
                <small>{desc}</small>
              </div>
              <ArrowUpRight size={16} />
            </button>
          ))}
        </section>
      </div>
      <section className="panel">
        <div className="section-head">
          <div>
            <h2>最近的邮箱记录</h2>
            <p>库存中的最新状态</p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => go("codes")}>
            查看全部
            <ArrowRight />
          </Button>
        </div>
        {query.isPending ? (
          <Loading />
        ) : !query.data?.items?.length ? (
          <Empty
            title="暂无邮箱记录"
            detail="同步云端别名或创建邮箱后，记录会显示在这里。"
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>邮箱地址</th>
                  <th>归属账号</th>
                  <th>状态</th>
                  <th>最近收件</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((item: Row) => (
                  <tr key={item.email}>
                    <td>
                      <span className="email-cell">
                        <Mail size={15} />
                        {item.email}
                      </span>
                    </td>
                    <td className="muted">{item.account_name || "—"}</td>
                    <td>
                      <Pill
                        value={
                          item.lifecycle_status === "disabled"
                            ? "disabled"
                            : item.group
                        }
                      />
                    </td>
                    <td className="muted">{stamp(item.last_received_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
function Login({ onLogin }: { onLogin: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <div className="login-page">
      <div className="login-brand">
        <Cloud />
        iCloud HME
      </div>
      <div className="login-card">
        <span className="login-symbol">
          <Mail size={26} />
        </span>
        <h1>欢迎回到工作台</h1>
        <p>登录后，继续管理你的隐私邮箱。</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.currentTarget));
            setBusy(true);
            setError(null);
            try {
              await post("/api/admin/login", data);
              onLogin();
            } catch (err) {
              setError(err);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="管理员账号">
            <input
              name="username"
              autoComplete="username"
              required
              placeholder="输入管理员账号"
            />
          </Field>
          <Field label="密码">
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              placeholder="输入密码"
            />
          </Field>
          <ErrorNotice error={error} />
          <Submit busy={busy}>
            登录工作台
            <ArrowRight size={16} />
          </Submit>
        </form>
        <small>
          <ShieldCheck size={14} />
          你的账号与邮件，由你掌握。
        </small>
      </div>
      <footer>iCloud Hide My Email · 多账号管理平台</footer>
    </div>
  );
}
function Docs() {
  return (
    <>
      <PageHead
        eyebrow="DEVELOPER"
        title="API 文档"
        description="在已登录的会话中调用接口，连接你的工作流。"
      />
      <div className="panel docs-list">
        {[
          ["GET", "/api/accounts", "账号列表"],
          [
            "GET",
            "/api/inventory?page=1&page_size=20&group=all",
            "分页查询库存；可增加 q 与 account_id 筛选",
          ],
          ["GET", "/api/inbox?limit=20&cache_only=1", "读取全部账号的邮件缓存"],
          ["GET", "/api/inbox/search?alias=邮箱地址", "查询指定隐私邮箱"],
          [
            "POST",
            "/api/create-batch",
            "批量创建：account_ids、count_per_account、label",
          ],
          [
            "POST",
            "/api/pickup-links/batch",
            "生成取码链接：emails、per_email",
          ],
          ["GET", "/api/logs?limit=100", "读取近期运行日志"],
        ].map(([method, path, desc]) => (
          <div key={path}>
            <span className={"method " + method}>{method}</span>
            <code>{path}</code>
            <p>{desc}</p>
          </div>
        ))}
      </div>
    </>
  );
}
