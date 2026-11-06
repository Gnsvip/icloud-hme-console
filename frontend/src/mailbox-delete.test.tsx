import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { Mailboxes } from "./pages/Mailboxes";

const row = { email: "gone@example.test", account_id: "account", anonymousId: "stale-id", group: "unused" };
const json = (data: unknown) => new Response(JSON.stringify(data), {
  headers: { "content-type": "application/json" },
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function openDeletion(result: object) {
  const fetcher = vi.fn((path: string) => Promise.resolve(json(path.endsWith("/delete")
    ? result : { ok: true, items: [row], count: 1, page: 1, pages: 1 })));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><Mailboxes mode="emails" accounts={[]} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 " + row.email }));
  fireEvent.click(screen.getByRole("button", { name: "删除别名" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认操作" }));
  return fetcher;
}

it("explains an already absent alias instead of claiming a new cloud deletion", async () => {
  const notify = vi.spyOn(toast, "success");
  const fetcher = await openDeletion({ ok: true, deleted: false, already_absent: true });
  await waitFor(() => expect(notify).toHaveBeenCalledWith("此账号的云端已无所选别名，本地记录已移入垃圾箱"));
  expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/delete"))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([path]) => path.startsWith("/api/inventory"))).toHaveLength(2);
});

it("retains the confirmation and selection if permanent deletion fails", async () => {
  const notify = vi.spyOn(toast, "success");
  const fetcher = await openDeletion({ ok: false, error: "别名已停用，但永久删除未完成" });
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "别名已停用，但永久删除未完成");
  expect(screen.getByRole("button", { name: "确认操作" })).toBeTruthy();
  expect(notify).not.toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(([path]) => path.startsWith("/api/inventory"))).toHaveLength(2);
});

it("permanently deletes selected trash records locally without cloud identifiers", async () => {
  let items = [{ email: "trash-a@example.test", group: "trash" }, { email: "trash-b@example.test", group: "trash" }];
  const fetcher = vi.fn((path: string) => {
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
