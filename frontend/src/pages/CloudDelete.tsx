import { useEffect, useRef, useState } from "react";
import { api, post, type Row } from "@/lib/api";
import { Button, ErrorNotice, Modal } from "@/components/common";

export const DELETE_JOB_KEY = "hme-cloud-delete-job";
const remember = (id: string) => { try { id ? sessionStorage.setItem(DELETE_JOB_KEY, id) : sessionStorage.removeItem(DELETE_JOB_KEY); } catch {} };
export function rememberedDeleteJob() { try { return sessionStorage.getItem(DELETE_JOB_KEY) || ""; } catch { return ""; } }

export function CloudDelete({ items, jobId, close, done }: {
  items: Row[]; jobId?: string; close: () => void; done: (job: Row) => void;
}) {
  const [job, setJob] = useState<Row | null>(jobId ? { job_id: jobId, state: "preparing", total: 0, completed: 0, items: [] } : null);
  const [error, setError] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(!!jobId);
  const [expired, setExpired] = useState(false);
  const requestId = useRef(crypto.randomUUID());
  const notified = useRef(false);
  const complete = job?.state === "complete";

  useEffect(() => {
    if (!job?.job_id || complete || expired) return;
    remember(job.job_id);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api(`/api/alias-deletions/${job.job_id}`, { signal: controller.signal, timeout: 10000 });
        if (controller.signal.aborted) return;
        setJob(next); setError(null);
        if (next.state !== "complete") timer = setTimeout(poll, 1000);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err);
        if (err.status === 410) { setExpired(true); remember(""); }
        else timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job?.job_id, complete, expired]);

  useEffect(() => {
    if (complete && !notified.current) {
      notified.current = true;
      done(job!);
    }
  }, [complete, job, done]);

  const dismiss = () => {
    if (busy) return;
    if (job && !complete && !expired) setHidden(true);
    else { remember(""); close(); }
  };
  const start = async () => {
    setBusy(true); setError(null); setHidden(true);
    try {
      const next = await post("/api/alias-deletions", {
        request_id: requestId.current,
        items: items.map(({ email, account_id, anonymousId }) => ({ email, account_id, anonymousId })),
      }, 15000);
      remember(next.job_id); setJob(next);
    } catch (err) {
      setError(err);
      if (err.status === 409) {
        try { const current = await api("/api/alias-deletions/active"); if (current.job) setJob(current.job); } catch {}
      }
    } finally { setBusy(false); }
  };

  if (hidden) return <div className="busy-strip" role="status">
    <span>{busy ? "正在提交云端删除…" : error || expired ? "云端删除状态需要核对" : complete ? `云端删除已完成 · 失败 ${job?.failed || 0}` : `云端删除进度 ${job?.completed || 0}/${job?.total || "…"}`}</span>
    <Button variant="outline" size="sm" onClick={() => setHidden(false)}>查看删除进度</Button>
    {(complete || expired) && <Button variant="ghost" size="sm" onClick={dismiss}>收起</Button>}
  </div>;

  return <Modal title={!job ? `删除 ${items.length} 个云端别名？` : complete ? "云端删除结果" : "正在删除云端别名"}
    description={!job ? "此操作会从 iCloud 删除选中的别名，并保留本地垃圾箱记录。请确认这些地址不再需要接收邮件。" : "任务在服务器执行，可暂时关闭窗口。刷新页面后可以继续查看进度。"}
    close={dismiss}>
    <ErrorNotice error={error} />
    {job && <div className="form-stack">
      <div role="status" aria-live="polite">
        <p>已处理 {job.completed} / {job.total || "…"} 个</p>
        <p>{job.state === "preparing" ? "正在读取云端列表…" : job.state === "syncing" ? "正在更新账号数量…" : complete ? "本批次已结束" : "正在向 Apple 提交删除…"}</p>
        <p>已删除 {job.deleted || 0} · 云端已不存在 {job.absent || 0} · 失败 {job.failed || 0}</p>
      </div>
      <progress aria-label="云端删除进度" value={job.completed} max={job.total || 1} style={{ width: "100%" }} />
      {job.warning && <p role="alert">{job.warning}</p>}
      <div style={{ maxHeight: "32vh", overflowY: "auto", overflowWrap: "anywhere" }}>
        {job.items.map((row: Row) => <p key={row.email}>
          {row.email} · {({ pending: "等待中", deleting: "删除中", deleted: "已删除", absent: "云端已不存在", failed: "失败" } as Row)[row.state]}
          {row.error && <span className="danger-text">：{row.error}</span>}
        </p>)}
      </div>
      {complete && job.failed > 0 && <p>失败的地址仍保留在列表中；同步云端后可重新选择这些地址重试。</p>}
    </div>}
    <div className="form-actions">
      <Button variant="outline" disabled={busy} onClick={dismiss}>{job ? complete || expired ? "关闭" : "后台继续" : "取消"}</Button>
      {!job && <Button variant="destructive" disabled={busy} onClick={() => void start()}>{busy ? "正在启动…" : "确认操作"}</Button>}
    </div>
  </Modal>;
}
