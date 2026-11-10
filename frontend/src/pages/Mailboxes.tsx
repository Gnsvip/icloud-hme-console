import { useEffect, useState } from "react";
import {
  Download,
  ExternalLink,
  Link2,
  Mail,
  MoreHorizontal,
  RefreshCw,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import { enc, stamp, useDebounced, useRemote, type Row } from "@/lib/api";
import {
  AccountSelect,
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
import { LinkGenerator } from "./Tools";
import { useBackgroundTasks } from "@/components/BackgroundTasks";
export function Mailboxes({
  mode,
  accounts,
}: {
  mode: string;
  accounts: Row[];
}) {
  const [group, setGroup] = useState(mode === "codes" ? "unused" : "all");
  const [search, setSearch] = useState(
    () => new URLSearchParams(location.hash.split("?")[1]).get("search") || "",
  );
  const q = useDebounced(search);
  const [account, setAccount] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [selected, setSelected] = useState<Record<string, Row>>({});
  const [actions, setActions] = useState<Row | null>(null);
  const [form, setForm] = useState<{ kind: string; rows: Row[] } | null>(null);
  const [links, setLinks] = useState<string | null>(null);
  const { enqueue, openCloud } = useBackgroundTasks();
  const [confirm, setConfirm] = useState<{
    title: string;
    description: string;
    run: () => Promise<any>;
  } | null>(null);
  const query = useRemote(
    `/api/inventory?group=${group}&q=${enc(q)}&account_id=${enc(account)}&page=${page}&page_size=${size}`,
  );
  const rows: Row[] = query.data?.items || [];
  const checked = Object.values(selected);
  const checkedAreTrash = checked.length > 0 && checked.every((row) => row.group === "trash");
  const effectivePage = query.data?.page || page;
  useEffect(() => {
    setPage(1);
  }, [q, account, group, size]);
  useEffect(() => {
    const update = () =>
      setSearch(
        new URLSearchParams(location.hash.split("?")[1]).get("search") || "",
      );
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    const completed = (event: Event) => setSelected(old => {
      const next = { ...old };
      for (const row of (event as CustomEvent).detail?.items || []) {
        if (["complete", "deleted", "absent"].includes(row.state)) delete next[row.email || row.label];
      }
      return next;
    });
    window.addEventListener("hme-task-complete", completed);
    return () => window.removeEventListener("hme-task-complete", completed);
  }, []);
  const toggle = (row: Row) =>
    setSelected((old) => {
      const next = { ...old };
      if (next[row.email]) delete next[row.email];
      else next[row.email] = row;
      return next;
    });
  const move = (items: Row[], target: string) => {
    enqueue("更新邮箱状态", items.map(row => ({ path: `/api/inventory/${enc(row.email)}/move`, body: { group: target }, label: row.email })));
    setSelected({}); setActions(null);
  };
  function deleteCloud(items: Row[]) {
    setActions(null); openCloud(items);
  }
  function purgeTrash(items: Row[]) {
    setActions(null);
    setConfirm({
      title: `永久删除 ${items.length} 条垃圾箱记录？`,
      description: "仅删除工作台中的记录，iCloud 云端邮箱不受影响。删除后无法恢复，也不会被同步自动加回。",
      run: async () => {
        if (items.some((row) => row.group !== "trash"))
          throw new Error("只能永久删除垃圾箱中的记录，请刷新列表。");
        enqueue("永久删除垃圾箱记录", items.map(row => ({ path: `/api/inventory/${enc(row.email)}/purge`, label: row.email })));
        setSelected({});
      },
    });
  }
  return (
    <>
      <PageHead
        eyebrow={mode === "codes" ? "CODE DESK" : "MAILBOXES"}
        title={mode === "codes" ? "验证码，随时就绪。" : "你的隐私邮箱。"}
        description={
          mode === "codes"
            ? "集中查看验证码与使用状态，快速找到需要的地址。"
            : "搜索、整理和管理所有账号的隐私邮箱。"
        }
      >
        <RefreshButton
          busy={query.isFetching}
          onClick={() => query.refetch()}
        />
        <Button
          onClick={() =>
            enqueue("云端同步", [{ path: "/api/inventory/sync", body: { live: true } }])
          }
        >
          <RefreshCw />云端同步
        </Button>
      </PageHead>
      <section className="panel mailbox-panel">
        <div className="tabs-row">
          {[
            ["all", "全部邮箱"],
            ["unused", "未使用"],
            ["finished", "已使用"],
            ["disabled", "已停用"],
            ["trash", "垃圾箱"],
          ].map(([key, label]) => (
            <button
              key={key}
              className={group === key ? "selected" : ""}
              onClick={() => { setGroup(key); setSelected({}); }}
            >
              {label}
              {group === key && query.data && <span>{query.data.count}</span>}
            </button>
          ))}
        </div>
        <div className="table-toolbar">
          <SearchBox value={search} onChange={setSearch} />
          <AccountSelect
            accounts={accounts}
            value={account}
            onChange={setAccount}
          />
          <div className="toolbar-spacer" />
          {mode === "codes" && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  enqueue("iCloud 查件", [{ path: "/api/inventory/check-icloud", body: { account_id: account, limit: 50, force: true } }])
                }
              >
                iCloud 查件
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  enqueue("转发查件", [{ path: "/api/inventory/check-forward", body: { account_id: account, limit: 50 } }])
                }
              >
                转发查件
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  enqueue("云端校准", [{ path: "/api/inventory/calibrate-cloud", body: { account_id: account, limit: 1500 } }])
                }
              >
                校准
              </Button>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              window.location.assign("/api/inventory/export?group=" + group)
            }
          >
            <Download />
            导出分组
          </Button>
        </div>
        {checked.length > 0 && (
          <div className="selection-bar">
            <span>
              <strong>{checked.length}</strong> 项已选择
            </span>
            <CopyButton
              value={checked.map((r) => r.email).join("\n")}
              label="复制"
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLinks(checked.map((r) => r.email).join("\n"))}
            >
              <Link2 />
              生成链接
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setForm({ kind: "label", rows: checked })}
            >
              <Tag />
              改标签
            </Button>
            <Button
              variant="ghost"
              size="sm"
                  onClick={() =>
                move(checked, group === "trash" ? "unused" : "finished")
              }
            >
              {group === "trash" ? "恢复" : "标记已使用"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
                  onClick={() => checkedAreTrash ? purgeTrash(checked) : deleteCloud(checked)}
            >
              <Trash2 />
              {checkedAreTrash ? "永久删除" : "删除别名"}
            </Button>
            <button
              className="selection-clear"
              aria-label="取消选择"
              onClick={() => setSelected({})}
            >
              <X size={16} />
            </button>
          </div>
        )}
        <ErrorNotice error={query.error} retry={query.refetch} />
        {query.isPending ? (
          <Loading />
        ) : !rows.length ? (
          <Empty
            title={q ? "没有找到匹配邮箱" : "这个分组还没有邮箱"}
            detail={
              q
                ? "试试其他地址、标签或备注。"
                : "可以先同步云端别名，或前往批量创建添加邮箱。"
            }
          />
        ) : (
          <div
            className={
              "table-wrap " + (query.isPlaceholderData ? "is-loading" : "")
            }
            aria-busy={query.isFetching}
          >
            <table className="mailbox-table">
              <thead>
                <tr>
                  <th className="check-cell">
                    <input
                      type="checkbox"
                      aria-label="选择本页邮箱"
                      disabled={query.isPlaceholderData}
                      checked={
                        rows.length > 0 && rows.every((r) => selected[r.email])
                      }
                      onChange={(e) => {
                        const on = e.target.checked;
                        setSelected((old) => {
                          const next = { ...old };
                          rows.forEach((r) => {
                            if (on) next[r.email] = r;
                            else delete next[r.email];
                          });
                          return next;
                        });
                      }}
                    />
                  </th>
                  <th>邮箱地址</th>
                  <th>状态</th>
                  {mode === "codes" ? (
                    <th>最新验证码</th>
                  ) : (
                    <th>标签 / 备注</th>
                  )}
                  <th>归属账号</th>
                  <th>最近收件</th>
                  <th className="action-cell" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.email} data-selected={!!selected[row.email]}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={"选择 " + row.email}
                        disabled={query.isPlaceholderData}
                        checked={!!selected[row.email]}
                        onChange={() => toggle(row)}
                      />
                    </td>
                    <td>
                      <div className="mailbox-address">
                        <span className="table-mail-icon">
                          <Mail size={15} />
                        </span>
                        <div>
                          <button
                            className="email-link"
                            onClick={() =>
                              (location.hash = "inbox?email=" + enc(row.email))
                            }
                          >
                            {row.email}
                          </button>
                          <small>
                            {mode === "codes"
                              ? row.subject || "等待邮件"
                              : row.label || "未设置标签"}
                          </small>
                        </div>
                        <CopyButton value={row.email} />
                      </div>
                    </td>
                    <td>
                      <Pill
                        value={
                          row.group === "trash"
                            ? "trash"
                            : row.lifecycle_status === "disabled"
                            ? "disabled"
                            : row.group
                        }
                      />
                    </td>
                    <td>
                      {mode === "codes" ? (
                        row.code ? (
                          <span className="verification-code">
                            {row.code}
                            <CopyButton value={row.code} />
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )
                      ) : (
                        <span className="label-text">
                          {row.remark || row.label || "—"}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="account-inline">
                        <i />
                        {row.account_name ||
                          accounts.find((a) => a.id === row.account_id)?.name ||
                          "—"}
                      </span>
                    </td>
                    <td className="muted nowrap">
                      {stamp(row.last_received_at)}
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={"操作 " + row.email}
                        disabled={query.isPlaceholderData}
                        onClick={() => setActions(row)}
                      >
                        <MoreHorizontal />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager
          page={effectivePage}
          pages={query.data?.pages || 1}
          total={query.data?.count || 0}
          onPage={setPage}
          size={size}
          onSize={setSize}
        />
      </section>
      {actions && (
        <Modal
          title="邮箱操作"
          description={actions.email}
          close={() => setActions(null)}
        >
          <div className="action-list">
            <button
              onClick={() => {
                location.hash = "inbox?email=" + enc(actions.email);
              }}
            >
              <Mail />
              查看邮件
              <ExternalLink size={14} />
            </button>
            <button
              onClick={() => {
                setLinks(actions.email);
                setActions(null);
              }}
            >
              <Link2 />
              生成取码链接
            </button>
            <button
              onClick={() => {
                setForm({ kind: "label", rows: [actions] });
                setActions(null);
              }}
            >
              <Tag />
              编辑云端标签
            </button>
            <button
              onClick={() => {
                setForm({ kind: "remark", rows: [actions] });
                setActions(null);
              }}
            >
              <Tag />
              编辑本地备注
            </button>
            <button
                  onClick={() =>
                move(
                  [actions],
                  actions.group === "finished" ? "unused" : "finished",
                )
              }
            >
              标记为{actions.group === "finished" ? "未使用" : "已使用"}
            </button>
            <button
                  onClick={() =>
                move([actions], actions.group === "trash" ? "unused" : "trash")
              }
            >
              {actions.group === "trash" ? "移出垃圾箱" : "移入垃圾箱"}
            </button>
            <button
              className="danger-text"
              onClick={() => deleteCloud([actions])}
            >
              <Trash2 />从 iCloud 删除别名
            </button>
            {actions.group === "trash" && (
              <button
                className="danger-text"
                onClick={() => purgeTrash([actions])}
              >
                永久删除本地记录
              </button>
            )}
          </div>
        </Modal>
      )}
      {form && (
        <TextEditor
          title={form.kind === "label" ? "编辑云端标签" : "编辑本地备注"}
          value={form.rows.length === 1 ? form.rows[0][form.kind] || "" : ""}
          close={() => setForm(null)}
          save={async (value) => {
            if (form.kind === "label" && form.rows.some(row => !row.anonymousId || !row.account_id))
              throw new Error("地址缺少云端标识，请先同步");
            enqueue(form.kind === "label" ? "更新云端标签" : "更新本地备注", form.rows.map(row => form.kind === "label"
              ? { path: `/api/accounts/${enc(row.account_id)}/aliases/${enc(row.anonymousId)}/label`, body: { label: value, email: row.email }, label: row.email }
              : { path: `/api/inventory/${enc(row.email)}/remark`, body: { remark: value }, label: row.email }));
            setForm(null);
          }}
        />
      )}
      {links !== null && (
        <LinkGenerator initial={links} close={() => setLinks(null)} />
      )}
      {confirm && (
        <Confirm
          title={confirm.title}
          description={confirm.description}
          close={() => setConfirm(null)}
          onConfirm={confirm.run}
        />
      )}
    </>
  );
}
function TextEditor({
  title,
  value,
  save,
  close,
}: {
  title: string;
  value: string;
  save: (v: string) => Promise<any>;
  close: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal title={title} close={close}>
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const value = String(
            new FormData(e.currentTarget).get("value") || "",
          );
          setBusy(true);
          try {
            await save(value);
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="内容">
          <input autoFocus name="value" defaultValue={value} />
        </Field>
        <ErrorNotice error={error} />
        <div className="form-actions">
          <Button variant="outline" type="button" onClick={close}>
            取消
          </Button>
          <Submit busy={busy} />
        </div>
      </form>
    </Modal>
  );
}
