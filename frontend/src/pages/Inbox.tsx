import { useBackgroundTasks } from "@/components/BackgroundTasks";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Mail,
  Search,
  Settings2,
} from "lucide-react";
import { enc, stamp, useRemote, type Row } from "@/lib/api";
import {
  AccountSelect,
  Button,
  CopyButton,
  Empty,
  ErrorNotice,
  Loading,
  RefreshButton,
} from "@/components/common";
import { PageHead } from "@/components/PageHead";
import { AccountForm } from "./Accounts";
import { MailBody, plainMailBody, readableMailText } from "@/lib/mail-body";
function messageKey(m: Row) {
  return m.account_id + ":" + m.id;
}
export function InboxPage({ accounts }: { accounts: Row[] }) {
  const client = useQueryClient();
  const { enqueue } = useBackgroundTasks();
  const initial =
    new URLSearchParams(location.hash.split("?")[1]).get("email") || "";
  const [account, setAccount] = useState("");
  const [limit, setLimit] = useState(20);
  const [input, setInput] = useState(initial);
  const [search, setSearch] = useState(initial);
  const [selected, setSelected] = useState<Row | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [settings, setSettings] = useState<Row | null>(null);
  const path = search
    ? `/api/inbox/search?alias=${enc(search)}&limit=${limit}`
    : account
      ? `/api/accounts/${enc(account)}/inbox?limit=${limit}&cache_only=1`
      : `/api/inbox?limit=${limit}&cache_only=1`;
  const query = useRemote(path, true, search ? 0 : 15000, !search);
  const messages: Row[] = query.data?.emails || [];
  // Account ID and message UID together are the identity; UIDs overlap across accounts.
  const bodyQuery = useRemote(
    selected?.account_id && selected?.id
      ? `/api/accounts/${enc(selected.account_id)}/message/${enc(selected.id)}`
      : "",
    !!selected?.account_id && !!selected?.id && !selected?.body,
  );
  const body =
    selected?.body ||
    (!bodyQuery.isPlaceholderData ? bodyQuery.data?.message?.body : "") ||
    "";
  const shownBody = body || selected?.body_preview || selected?.preview || "暂无正文";
  const bodyTruncated = selected?.body ? selected.body_truncated : !bodyQuery.isPlaceholderData && bodyQuery.data?.message?.body_truncated;
  useEffect(() => { setShowRaw(false); }, [selected?.account_id, selected?.id]);
  useEffect(() => {
    setSelected(null);
  }, [account, search]);
  useEffect(() => {
    if (selected) {
      const newer = messages.find(
        (m) => messageKey(m) === messageKey(selected),
      );
      if (newer?.body && !selected.body) setSelected(newer);
    }
  }, [query.data]);
  useEffect(() => {
    const update = () => {
      const email =
        new URLSearchParams(location.hash.split("?")[1]).get("email") || "";
      setInput(email);
      setSearch(email);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const refresh = async () => {
    if (search) {
      query.refetch();
      return;
    }
    enqueue("刷新收件箱", [{ path: path.replace("cache_only=1", account ? "force=1" : "refresh=1"), method: "GET" }]);
  };
  return (
    <>
      <PageHead
        eyebrow="INBOX"
        title="收件箱"
        description="邮件与正文分栏查看。自动读取本地缓存，点击刷新获取云端新邮件。"
      >
        <Button
          variant="outline"
          disabled={!accounts.length}
          onClick={() =>
            setSettings(accounts.find((a) => a.id === account) || accounts[0])
          }
        >
          <Settings2 />
          收件设置
        </Button>
        <RefreshButton
          busy={query.isFetching}
          onClick={refresh}
        />
      </PageHead>
      <section className="panel inbox-panel">
        <div className="inbox-toolbar-v2">
          <AccountSelect
            accounts={accounts}
            value={account}
            onChange={setAccount}
          />
          <select
            aria-label="邮件数量"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                最近 {n} 封
              </option>
            ))}
          </select>
          <form
            className="search-field"
            onSubmit={(e) => {
              e.preventDefault();
              if (input.trim() === search) query.refetch();
              else setSearch(input.trim());
            }}
          >
            <Search size={16} />
            <input
              aria-label="按邮箱地址查件"
              placeholder="输入完整邮箱地址查件…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            <button type="submit">查件</button>
          </form>
          {search && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch("");
                setInput("");
              }}
            >
              退出搜索
            </Button>
          )}
        </div>
        <ErrorNotice error={query.error} retry={refresh} />
        {query.data?.errors?.length > 0 && (
          <div className="error-notice">
            部分账号未能刷新：{query.data.errors.join("；")}
          </div>
        )}
        <div className={"inbox-split " + (selected ? "has-selection" : "")}>
          <div className="message-list">
            <div className="message-list-header">
              <strong>{search ? "搜索结果" : "最新邮件"}</strong>
              <span>
                {messages.length} 封 {query.isFetching ? "· 更新中" : " "}
              </span>
            </div>
            {query.isPending ? (
              <Loading />
            ) : !messages.length ? (
              <Empty
                title={search ? "没有找到邮件" : "收件箱暂无邮件"}
                detail={
                  search
                    ? "确认邮箱地址，或稍后重新查询。"
                    : "点击右上角刷新，从 iCloud 获取最新邮件。"
                }
              />
            ) : (
              messages.map((m) => (
                <button
                  key={messageKey(m)}
                  disabled={query.isPlaceholderData}
                  className={
                    "message-row " +
                    (selected && messageKey(selected) === messageKey(m)
                      ? "active"
                      : "")
                  }
                  onClick={() => setSelected(m)}
                >
                  <div className="message-row-top">
                    <span className="sender-avatar">
                      {String(m.from || "M")
                        .replace(/[<"']/g, "")
                        .slice(0, 1)
                        .toUpperCase()}
                    </span>
                    <strong>
                      {String(m.from || "未知发件人")
                        .split("<")[0]
                        .replace(/"/g, "")
                        .trim()}
                    </strong>
                    <time>{stamp(m.internal_date || m.date)}</time>
                  </div>
                  <h3>{m.subject || "（无主题）"}</h3>
                  <p>
                    {readableMailText(
                      m.body_preview ||
                        m.preview ||
                        m.body ||
                        "点击查看邮件正文",
                    ).slice(0, 100)}
                  </p>
                  <small>{m.to || m.account_icloud_email || "—"}</small>
                </button>
              ))
            )}
          </div>
          <article className="message-reader">
            {!selected ? (
              <div className="reader-empty">
                <div>
                  <Mail size={32} />
                </div>
                <h2>选择一封邮件</h2>
                <p>在左侧选择邮件，即可查看完整内容。</p>
                <span>邮件会在当前页面内打开</span>
              </div>
            ) : (
              <>
                <div className="reader-toolbar">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="reader-back"
                    onClick={() => setSelected(null)}
                  >
                    <ArrowLeft />
                    返回
                  </Button>
                  <span>邮件详情</span>
                  <div />
                  <Button variant="ghost" size="sm" aria-pressed={showRaw} onClick={() => setShowRaw(!showRaw)}>{showRaw ? "易读模式" : "显示原文"}</Button>
                  <CopyButton value={showRaw ? plainMailBody(body) : readableMailText(body)} label="复制正文" />
                </div>
                <div className="reader-header">
                  <h2>{selected.subject || "（无主题）"}</h2>
                  <div className="reader-meta">
                    <span className="sender-avatar">
                      {String(selected.from || "M")
                        .replace(/[<"']/g, "")
                        .slice(0, 1)
                        .toUpperCase()}
                    </span>
                    <div>
                      <strong>{selected.from || "未知发件人"}</strong>
                      <p>收件人：{selected.to || "—"}</p>
                      <p>
                        账号：
                        {selected.account_icloud_email ||
                          accounts.find((a) => a.id === selected.account_id)
                            ?.name ||
                          "—"}
                      </p>
                    </div>
                    <time>
                      {stamp(selected.internal_date || selected.date)}
                    </time>
                  </div>
                  {selected.code && (
                    <div className="code-callout">
                      <span>验证码</span>
                      <strong>{selected.code}</strong>
                      <CopyButton value={selected.code} />
                    </div>
                  )}
                </div>
                <ErrorNotice
                  error={!selected.body && bodyQuery.error}
                  retry={bodyQuery.refetch}
                />
                {!selected.body && bodyQuery.isFetching && !body ? (
                  <Loading />
                ) : (
                  <div className="reader-body">
                    {showRaw ? plainMailBody(shownBody) : <MailBody value={shownBody} />}
                    {bodyTruncated && <p className="muted">邮件较长，当前显示前部分正文。</p>}
                  </div>
                )}
              </>
            )}
          </article>
        </div>
      </section>
      {settings && (
        <AccountForm
          account={settings}
          close={() => setSettings(null)}
          done={() => {
            setSettings(null);
            client.invalidateQueries({ queryKey: ["/api/accounts"] });
            refresh();
          }}
        />
      )}
    </>
  );
}
