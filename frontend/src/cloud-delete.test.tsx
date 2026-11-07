import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CloudDelete, DELETE_JOB_KEY } from "./pages/CloudDelete";

const items = [{ email: "demo@example.test", account_id: "one", anonymousId: "id" }];
const active = { ok: true, job_id: "synthetic", state: "deleting", total: 1, completed: 0, items: [{ ...items[0], state: "deleting" }] };
const json = (value: any, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => { sessionStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("shows progress, keeps polling in background, and never reposts on remount", async () => {
  const fetcher = vi.fn((path: string) => Promise.resolve(json(active)));
  vi.stubGlobal("fetch", fetcher);
  const first = render(<CloudDelete items={items} close={vi.fn()} done={vi.fn()} />);
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "确认操作" })); });
  expect(screen.getByText("已处理 0 / 1 个")).toBeTruthy();
  expect(sessionStorage.getItem(DELETE_JOB_KEY)).toBe("synthetic");
  fireEvent.click(screen.getByRole("button", { name: "后台继续" }));
  expect(screen.getByRole("button", { name: "查看删除进度" })).toBeTruthy();
  first.unmount();
  const done = vi.fn();
  fetcher.mockResolvedValue(json({ ...active, state: "complete", completed: 1, deleted: 1, items: [{ ...items[0], state: "deleted" }] }));
  await act(async () => { render(<CloudDelete items={[]} jobId="synthetic" close={vi.fn()} done={done} />); });
  expect(screen.getByText("已处理 1 / 1 个")).toBeTruthy();
  expect(done).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/alias-deletions")).toHaveLength(1);
});

it("retains the submission identifier when the initial response is lost", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("network failure")).mockResolvedValue(json(active));
  vi.stubGlobal("fetch", fetcher);
  render(<CloudDelete items={items} close={vi.fn()} done={vi.fn()} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "确认操作" })); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "确认操作" })); });
  const posts = fetcher.mock.calls.filter(([path]) => path === "/api/alias-deletions");
  expect(posts).toHaveLength(2);
  expect(JSON.parse(posts[0][1].body).request_id).toBe(JSON.parse(posts[1][1].body).request_id);
});
