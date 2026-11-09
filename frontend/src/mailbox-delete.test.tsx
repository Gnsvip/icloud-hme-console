import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Mailboxes } from "./pages/Mailboxes";

const row = { email: "gone@example.test", account_id: "account", anonymousId: "stale-id", group: "unused" };
const json = (data: unknown) => new Response(JSON.stringify(data), {
  headers: { "content-type": "application/json" },
});
beforeEach(() => { sessionStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("shows Trash instead of the historical disabled badge for deleted records", async () => {
  vi.stubGlobal("fetch", vi.fn((path: string) => Promise.resolve(json(path === "/api/alias-deletions/active"
    ? { ok: true, job: null }
    : { ok: true, items: [{ ...row, group: "trash", lifecycle_status: "disabled" }], count: 1, page: 1, pages: 1 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><Mailboxes mode="emails" accounts={[]} /></QueryClientProvider>);
  const entry = await screen.findByRole("row", { name: /gone@example.test/ });
  expect(within(entry).getByText("垃圾箱")).toBeTruthy();
  expect(within(entry).queryByText("已停用")).toBeNull();
});

async function openDeletion(result: object) {
  const fetcher = vi.fn((path: string) => Promise.resolve(json(path === "/api/alias-deletions/active"
    ? { ok: true, job: null } : path === "/api/alias-deletions" ? result
      : { ok: true, items: [row], count: 1, page: 1, pages: 1 })));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><Mailboxes mode="emails" accounts={[]} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 " + row.email }));
  fireEvent.click(screen.getByRole("button", { name: "删除别名" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认操作" }));
  return fetcher;
}

it("explains an already absent alias instead of claiming a new cloud deletion", async () => {
  const fetcher = await openDeletion({ ok: true, job_id: "batch-one", state: "complete", total: 1, completed: 1, deleted: 0, absent: 1, failed: 0, items: [{ ...row, state: "absent" }] });
  expect(await screen.findByRole("heading", { name: "云端删除结果" })).toBeTruthy();
  expect(screen.getByText("已删除 0 · 云端已不存在 1 · 失败 0")).toBeTruthy();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/alias-deletions")).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([path]) => path.startsWith("/api/inventory"))).toHaveLength(2);
});

it("shows failed results without automatically repeating deletion", async () => {
  const fetcher = await openDeletion({ ok: true, job_id: "batch-one", state: "complete", total: 1, completed: 1, deleted: 0, absent: 0, failed: 1, items: [{ ...row, state: "failed", error: "别名已停用，但永久删除未完成" }] });
  expect(await screen.findByText(/别名已停用，但永久删除未完成/)).toBeTruthy();
  expect(screen.getByText(/失败的地址仍保留/)).toBeTruthy();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/alias-deletions")).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([path]) => path.startsWith("/api/inventory"))).toHaveLength(2);
});

it("permanently deletes selected trash records locally without cloud identifiers", async () => {
  let items = [{ email: "trash-a@example.test", group: "trash" }, { email: "trash-b@example.test", group: "trash" }];
  const fetcher = vi.fn((path: string) => {
    if (path === "/api/alias-deletions/active") return Promise.resolve(json({ ok: true, job: null }));
    if (path.endsWith("/purge")) {
      items = items.filter((item) => !path.includes(encodeURIComponent(item.email)));
      return Promise.resolve(json({ ok: true }));
    }
    return Promise.resolve(json({ ok: true, items, count: items.length, page: 1, pages: 1 }));
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><Mailboxes mode="emails" accounts={[]} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择本页邮箱" }));
  fireEvent.click(screen.getByRole("button", { name: "永久删除" }));
  expect(await screen.findByRole("heading", { name: "永久删除 2 条垃圾箱记录？" })).toBeTruthy();
  expect(screen.getByText(/iCloud 云端邮箱不受影响/)).toBeTruthy();
  expect(fetcher.mock.calls.some(([path]) => path.endsWith("/purge"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "确认操作" }));
  expect(await screen.findByText("这个分组还没有邮箱")).toBeTruthy();
  expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/purge"))).toHaveLength(2);
  expect(fetcher.mock.calls.some(([path]) => path.startsWith("/api/accounts/"))).toBe(false);
});
