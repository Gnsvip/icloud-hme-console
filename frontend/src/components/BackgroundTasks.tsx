import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, post, type Row } from "@/lib/api";
import { Button, ErrorNotice, Modal } from "./common";
import { CloudDelete, rememberedDeleteJob } from "@/pages/CloudDelete";

export type TaskStep = { path: string; body?: Row; method?: "GET" | "POST"; label?: string };
type Task = { id: string; title: string; steps?: TaskStep[] };
const STORAGE_KEY = "hme-background-tasks";
function restoredTasks(): Task[] {
  try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "[]").filter((t: Task) => typeof t.id === "string" && typeof t.title === "string").slice(-50); }
  catch { return []; }
}
type Context = { enqueue: (title: string, steps: TaskStep[]) => void; openCloud: (items: Row[]) => void; tasks: Task[]; remove: (id: string) => void; cloud: { items: Row[]; jobId?: string; key?: string; complete?: boolean } | null; closeCloud: () => void; finishCloud: () => void };
const TaskContext = createContext<Context | null>(null);
export function useBackgroundTasks() {
  const context = useContext(TaskContext);
  if (!context) throw new Error("后台任务服务未加载");
  return context;
}

export function BackgroundTasksProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<Task[]>(restoredTasks);
  const [cloud, setCloud] = useState<Context["cloud"]>(() => {
    const jobId = rememberedDeleteJob();
    return jobId ? { items: [], jobId } : null;
  });
  useEffect(() => {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(tasks.map(({ id, title }) => ({ id, title })))); } catch {}
  }, [tasks]);
  useEffect(() => {
    const controller = new AbortController();
    void api("/api/background-tasks/active", { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setTasks(old => [...old, ...(data.jobs || []).filter((j: Row) => !old.some(t => t.id === j.job_id)).map((j: Row) => ({ id: j.job_id, title: j.title }))]);
    }).catch(() => {});
    void api("/api/alias-deletions/active", { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted && data.job) setCloud(old => old || { items: [], jobId: data.job.job_id });
    }).catch(() => {});
    return () => controller.abort();
  }, []);
  const enqueue = (title: string, steps: TaskStep[]) => {
    const task = { id: crypto.randomUUID(), title, steps };
    setTasks(old => [...old, task]);
  };
  const openCloud = (items: Row[]) => {
    if (cloud && !cloud.complete) { toast.info("已有云端删除任务，请查看顶部的删除进度"); return; }
    setCloud({ items, key: crypto.randomUUID() });
  };
  return <TaskContext.Provider value={{ tasks, enqueue, cloud, openCloud, closeCloud: () => setCloud(null), finishCloud: () => setCloud(old => old ? { ...old, complete: true } : null), remove: id => setTasks(old => old.filter(t => t.id !== id)) }}>{children}</TaskContext.Provider>;
}

export function BackgroundTaskBar({ creation }: { creation?: Row }) {
  const { tasks, remove, cloud, closeCloud, finishCloud } = useBackgroundTasks();
  const client = useQueryClient();
  const previousCreation = useRef(false);
  const refresh = () => void client.invalidateQueries();
  useEffect(() => {
    if (previousCreation.current && !creation?.creating) {
      creation?.last_error ? toast.warning("创建任务已结束，请查看批量创建页的结果") : toast.success(`创建任务已完成，本轮创建 ${creation?.current_round_created || 0} 个`);
      refresh();
    }
    previousCreation.current = !!creation?.creating;
  }, [creation?.creating]);
  if (!tasks.length && !cloud && !creation?.creating) return null;
  return <section className="background-tasks" aria-label="后台任务">
    {creation?.creating && <div className="background-task-row" role="status"><span>{creation.round_status || "正在后台创建邮箱"} · 已创建 {creation.current_round_created || 0} 个</span><a href="#batch">查看创建任务</a></div>}
    {cloud && <CloudDelete key={cloud.key || cloud.jobId || "draft"} items={cloud.items} jobId={cloud.jobId} close={closeCloud} done={(job) => {
      finishCloud();
      refresh();
      window.dispatchEvent(new CustomEvent("hme-task-complete", { detail: job }));
      const message = `云端删除已完成：已删除 ${job.deleted || 0}，已不存在 ${job.absent || 0}，失败 ${job.failed || 0}`;
      job.failed || job.warning || job.items?.some((r: Row) => r.error) ? toast.warning(message) : toast.success(message);
    }} />}
    {tasks.map(task => <TaskTracker key={task.id} task={task} remove={() => remove(task.id)} />)}
  </section>;
}

function TaskTracker({ task, remove }: { task: Task; remove: () => void }) {
  const client = useQueryClient();
  const [job, setJob] = useState<Row | null>(null);
  const [submitting, setSubmitting] = useState(!!task.steps);
  const [error, setError] = useState<any>(null);
  const [expired, setExpired] = useState(false);
  const [details, setDetails] = useState(false);
  const submitted = useRef(false), notified = useRef(false), inflight = useRef(false);
  const complete = job?.state === "complete";
  const jobId = job?.job_id || task.id;
  const submit = async () => {
    if (inflight.current) return;
    inflight.current = true;
    setSubmitting(true); setError(null); setExpired(false);
    try { setJob(await post("/api/background-tasks", { request_id: task.id, title: task.title, steps: task.steps }, 15000)); }
    catch (err) { setError(err); if (err.status >= 400 && err.status < 500) setExpired(true); toast.error(`${task.title}提交未确认，请查看后台任务`); }
    finally { inflight.current = false; setSubmitting(false); }
  };
  useEffect(() => {
    if (task.steps && !submitted.current) { submitted.current = true; void submit(); }
  }, []);
  useEffect(() => {
    if (submitting || complete || expired) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api(`/api/background-tasks/${encodeURIComponent(jobId)}`, { signal: controller.signal, timeout: 10000 });
        if (controller.signal.aborted) return;
        setJob(next); setError(null);
        if (next.state !== "complete") timer = setTimeout(poll, 1500);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err);
        if (err.status === 410) setExpired(true);
        else timer = setTimeout(poll, 4000);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId, submitting, complete, expired]);
  useEffect(() => {
    if (!complete || notified.current) return;
    notified.current = true;
    void client.invalidateQueries();
    window.dispatchEvent(new CustomEvent("hme-task-complete", { detail: job }));
    const message = job!.failed ? `${task.title}已结束：${job!.failed} 项未完成，请查看详情` : `${task.title}已完成`;
    job!.failed ? toast.warning(message) : toast.success(message);
  }, [complete, job, client, task.title]);
  const status = submitting ? "正在提交…" : error ? "状态需要核对" : complete ? job?.failed ? `${job.failed} 项未完成` : "已完成" : job?.state === "queued" ? "排队中" : `后台执行中 ${job?.completed || 0}/${job?.total || task.steps?.length || "…"}`;
  return <>
    <div className="background-task-row" role="status">
      <span><strong>{task.title}</strong> · {status}</span>
      <div><Button variant="ghost" size="sm" onClick={() => setDetails(true)}>查看详情</Button>{(complete || expired) && <Button variant="ghost" size="sm" onClick={remove}>收起</Button>}</div>
    </div>
    {details && <Modal title={task.title} description="任务在服务器后台执行，关闭窗口或切换页面不会中断任务。" close={() => setDetails(false)}>
      <p>{status}</p><ErrorNotice error={error} />
      {!complete && !expired && <progress aria-label="任务进度" value={job?.completed || 0} max={job?.total || 1} style={{ width: "100%" }} />}
      <div className="background-task-details">{job?.items?.map((row: Row, index: number) => <p key={index}>{row.label} · {({ pending: "等待中", running: "执行中", complete: "已完成", failed: "未完成" } as Row)[row.state]}{row.error && <span className="danger-text">：{row.error}</span>}{row.message && <span>：{row.message}</span>}</p>)}</div>
      {expired && <p>请刷新相关列表核对实际结果。系统不会自动重复执行。</p>}
      <div className="form-actions">{!job && error && task.steps && <Button variant="outline" disabled={submitting} onClick={() => void submit()}>重新确认提交</Button>}<Button onClick={() => setDetails(false)}>关闭</Button></div>
    </Modal>}
  </>;
}
