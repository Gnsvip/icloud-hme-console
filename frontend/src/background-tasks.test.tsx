import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { BackgroundTaskBar, BackgroundTasksProvider, useBackgroundTasks } from "./components/BackgroundTasks";

const json = (value: any, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
beforeEach(() => {
  sessionStorage.clear(); location.hash = "emails";
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });

it("closes the trash confirmation immediately and completes after navigating to another page", async () => {
  let accept: (value: Response) => void;
  let job: any;
  let items = [{ email: "trash@example.test", group: "trash", account_id: "a" }];
  const fetcher = vi.fn((path: string, options: any) => {
    if (path.endsWith("/active")) return Promise.resolve(json({ ok: true, jobs: [], job: null }));
    if (path === "/api/background-tasks") {
      const request = JSON.parse(options.body);
      job = { ok: true, job_id: request.request_id, title: request.title, state: "running", total: 1, completed: 0, failed: 0, items: [] };
      return new Promise<Response>(resolve => { accept = resolve; });
    }
    if (path.startsWith("/api/background-tasks/")) return Promise.resolve(json(job));
    if (path.startsWith("/api/inventory?")) return Promise.resolve(json({ ok: true, items, count: items.length, page: 1, pages: 1 }));
    return Promise.resolve(json({ ok: true, accounts: [{ id: "a", name: "测试账号" }], emails: [] }));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<QueryClientProvider client={client()}><App /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 trash@example.test" }));
  fireEvent.click(screen.getByRole("button", { name: "永久删除" }));
  fireEvent.click(screen.getByRole("button", { name: "确认操作" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByText(/正在提交/)).toBeTruthy();
  act(() => { location.hash = "accounts"; window.dispatchEvent(new Event("hashchange")); });
  expect(await screen.findByRole("heading", { name: "账号管理" })).toBeTruthy();
  job = { ...job, state: "complete", completed: 1, items: [{ label: "trash@example.test", state: "complete" }] };
  items = [];
  await act(async () => { accept(json(job)); });
  expect(await screen.findByText(/永久删除垃圾箱记录/)).toBeTruthy();
  expect(screen.getByText(/· 已完成/)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  act(() => { location.hash = "emails"; window.dispatchEvent(new Event("hashchange")); });
  expect(await screen.findByText("这个分组还没有邮箱")).toBeTruthy();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/background-tasks")).toHaveLength(1);
  expect(fetcher.mock.calls.some(([path]) => path.endsWith("/purge"))).toBe(false);
});

function Trigger() {
  const { enqueue } = useBackgroundTasks();
  return <button onClick={() => enqueue("云端同步", [{ path: "/api/inventory/sync", body: { live: true } }])}>启动测试任务</button>;
}
function Harness() { return <QueryClientProvider client={client()}><BackgroundTasksProvider><BackgroundTaskBar /><Trigger /></BackgroundTasksProvider></QueryClientProvider>; }

it("restores a running task after refresh without resubmitting and keeps partial failures visible", async () => {
  let completed = false;
  const base = { ok: true, job_id: "restored-task", title: "云端同步", total: 2, completed: 0, items: [], state: "running" };
  sessionStorage.setItem("hme-background-tasks", JSON.stringify([{ id: base.job_id, title: base.title }]));
  const fetcher = vi.fn((path: string) => Promise.resolve(json(path.endsWith("/active") ? { ok: true, job: null, jobs: [base] } : completed
    ? { ...base, state: "complete", completed: 2, failed: 1, items: [{ label: "账号 A", state: "complete" }, { label: "账号 B", state: "failed", error: "连接失败，请稍后手动重试" }] } : base)));
  vi.stubGlobal("fetch", fetcher);
  const first = render(<Harness />);
  expect(await screen.findByText(/后台执行中 0\/2/)).toBeTruthy();
  first.unmount(); completed = true;
  render(<Harness />);
  expect(await screen.findByText(/1 项未完成/)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
  expect(screen.getByText(/连接失败，请稍后手动重试/)).toBeTruthy();
  expect(fetcher.mock.calls.some(([path]) => path === "/api/background-tasks")).toBe(false);
});

it("recovers the accepted task when its submission response was lost", async () => {
  let id = "";
  const fetcher = vi.fn((path: string, options: any) => {
    if (path.endsWith("/active")) return Promise.resolve(json({ ok: true, jobs: [], job: null }));
    if (path === "/api/background-tasks") { id = JSON.parse(options.body).request_id; return Promise.reject(new Error("response lost")); }
    return Promise.resolve(json({ ok: true, job_id: id, state: "complete", total: 1, completed: 1, failed: 0, items: [] }));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "启动测试任务" }));
  expect(await screen.findByText(/· 已完成/)).toBeTruthy();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/background-tasks")).toHaveLength(1);
});

it("shows a rejected operation without retrying it or hiding the error", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(json(path.endsWith("/active") ? { ok: true, jobs: [], job: null } : { ok: false, error: "后台任务已满，请稍后再提交" }, path.endsWith("/active") ? 200 : 409)));
  vi.stubGlobal("fetch", fetcher);
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "启动测试任务" }));
  expect(await screen.findByText(/状态需要核对/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
  expect(screen.getByText("后台任务已满，请稍后再提交")).toBeTruthy();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/background-tasks")).toHaveLength(1);
});
