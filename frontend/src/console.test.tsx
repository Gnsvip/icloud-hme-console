import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  focusManager,
} from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { api, useRemote } from "./lib/api";
import { InboxPage } from "./pages/Inbox";
import { Batch } from "./pages/Tools";
import { Mailboxes } from "./pages/Mailboxes";
import App from "./App";
function json(data: any, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}
function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retryDelay: 1, gcTime: 0 } },
  });
  return {
    client,
    Wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}
const accounts = [
  { id: "a", name: "测试账号 A", status: "active" },
  { id: "b", name: "测试账号 B", status: "active" },
];
describe("lazy console pages", () => {
  it("opens inbox and accounts through the application shell", async () => {
    location.hash = "inbox";
    vi.stubGlobal("fetch", vi.fn((path: string) => Promise.resolve(json(
      path === "/api/accounts" ? { accounts } : { ok: true, emails: [] },
    ))));
    const { Wrapper } = wrapper();
    render(<Wrapper><App /></Wrapper>);
    expect(await screen.findByRole("heading", { name: "收件箱" })).toBeTruthy();
    act(() => {
      location.hash = "accounts";
      window.dispatchEvent(new Event("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "账号管理" })).toBeTruthy();
  });
  it("keeps private queries disabled before login", async () => {
    const fetcher = vi.fn(() => Promise.resolve(json({ ok: false })));
    vi.stubGlobal("fetch", fetcher);
    const { Wrapper } = wrapper();
    render(<Wrapper><App /></Wrapper>);
    expect(await screen.findByRole("button", { name: /登录工作台/ })).toBeTruthy();
    expect(fetcher.mock.calls).toHaveLength(1);
    expect((fetcher.mock.calls as any[])[0][0]).toBe("/api/admin/session");
  });
});
beforeEach(() => {
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
    clear: () => storage.clear(),
  });
  location.hash = "";
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
  focusManager.setFocused(true);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  focusManager.setFocused(undefined);
});
describe("request lifecycle", () => {
  it("keeps displayed data when a refresh fails", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        json({ ok: true, items: [{ email: "retained@icloud.com" }] }),
      );
    vi.stubGlobal("fetch", fetcher);
    const { Wrapper } = wrapper();
    const hook = renderHook(
      () => {
        const q = useRemote("/api/inventory");
        return { data: q.data, error: q.error, refetch: q.refetch };
      },
      { wrapper: Wrapper },
    );
    await waitFor(() =>
      expect(hook.result.current.data?.items).toHaveLength(1),
    );
    fetcher.mockRejectedValue(new Error("offline"));
    await act(async () => {
      await hook.result.current.refetch();
    });
    await waitFor(() =>
      expect(hook.result.current.error?.message).toBe("offline"),
    );
    expect(hook.result.current.data?.items[0].email).toBe(
      "retained@icloud.com",
    );
  });
  it("stops interval requests while the document is hidden", async () => {
    const fetcher = vi
      .fn()
      .mockImplementation(() => Promise.resolve(json({ ok: true })));
    vi.stubGlobal("fetch", fetcher);
    const { Wrapper } = wrapper();
    const hook = renderHook(() => useRemote("/api/state", true, 40), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
    act(() => {
      Object.defineProperty(document, "hidden", {
        value: true,
        configurable: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const before = fetcher.mock.calls.length;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 130));
    });
    expect(fetcher).toHaveBeenCalledTimes(before);
  });
  it("invalidates the session on a protected 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ok: false }, 401)));
    const expired = vi.fn();
    window.addEventListener("hme-session-expired", expired);
    await expect(api("/api/accounts")).rejects.toThrow("登录已过期");
    expect(expired).toHaveBeenCalledTimes(1);
    window.removeEventListener("hme-session-expired", expired);
  });
  it("cancels an in-flight request when its owner aborts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_p, options) =>
          new Promise((_resolve, reject) =>
            options.signal.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            ),
          ),
      ),
    );
    const controller = new AbortController();
    const pending = api("/api/inbox", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toThrow("已取消");
  });
});
describe("mail and inventory interactions", () => {
  it("offers readable and original bodies and resets the view for another email", async () => {
    const url = "https://tracking.example.test/click?token=" + "long-token-".repeat(100);
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({ ok: true, emails: [
      { id: "1", account_id: "a", subject: "Long link message", body: `正文 (${url})\n最后一段` },
      { id: "2", account_id: "a", subject: "Other message", body: "另一封邮件" },
    ] }))));
    const { Wrapper } = wrapper();
    render(<Wrapper><InboxPage accounts={accounts} /></Wrapper>);
    fireEvent.click(await screen.findByRole("button", { name: /Long link message/ }));
    expect(screen.getByRole("link", { name: "链接：tracking.example.test" }).getAttribute("href")).toBe(url);
    fireEvent.click(screen.getByRole("button", { name: "显示原文" }));
    expect(screen.getByRole("button", { name: "易读模式" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(new RegExp("long-token-"))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Other message/ }));
    expect(screen.getByRole("button", { name: "显示原文" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("uses account plus UID and never shows the previous account body", async () => {
    let resolveBody: (v: Response) => void;
    const fetcher = vi.fn((path: string) => {
      if (path.includes("/message/") && path.includes("/a/"))
        return Promise.resolve(
          json({ ok: true, message: { body: "Account A body" } }),
        );
      if (path.includes("/message/") && path.includes("/b/"))
        return new Promise<Response>((resolve) => {
          resolveBody = resolve;
        });
      return Promise.resolve(
        json({
          ok: true,
          emails: [
            { id: "7", account_id: "a", subject: "Mail A", from: "Sender A" },
            { id: "7", account_id: "b", subject: "Mail B", from: "Sender B" },
          ],
        }),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    const { Wrapper } = wrapper();
    render(
      <Wrapper>
        <InboxPage accounts={accounts} />
      </Wrapper>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Mail A/ }));
    await screen.findByText("Account A body");
    fireEvent.click(screen.getByRole("button", { name: /Mail B/ }));
    expect(screen.queryByText("Account A body")).toBeNull();
    await waitFor(() => expect(resolveBody).toBeTypeOf("function"));
    await act(async () =>
      resolveBody(json({ ok: true, message: { body: "Account B body" } })),
    );
    expect(await screen.findByText("Account B body")).toBeTruthy();
  });
  it("does not refresh a mailbox search on window focus", async () => {
    location.hash = "inbox?email=sample%40icloud.com";
    const fetcher = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(json({ ok: true, emails: [] })),
      );
    vi.stubGlobal("fetch", fetcher);
    const { client, Wrapper } = wrapper();
    render(
      <Wrapper>
        <InboxPage accounts={accounts} />
      </Wrapper>,
    );
    await screen.findByText("没有找到邮件");
    await act(async () => {
      await client.invalidateQueries({ refetchType: "none" });
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("requests inventory pages from the server and keeps cross-page selections", async () => {
    const fetcher = vi.fn((path: string) => {
      const page = new URL(path, "http://local").searchParams.get("page");
      return Promise.resolve(
        json({
          ok: true,
          count: 21,
          pages: 2,
          page: Number(page),
          items: [
            {
              email: page === "2" ? "last@icloud.com" : "first@icloud.com",
              group: "unused",
              account_id: "a",
            },
          ],
        }),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    const { Wrapper } = wrapper();
    render(
      <Wrapper>
        <Mailboxes mode="emails" accounts={accounts} />
      </Wrapper>,
    );
    fireEvent.click(
      await screen.findByRole("checkbox", { name: "选择 first@icloud.com" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByRole("checkbox", { name: "选择 last@icloud.com" });
    expect(screen.getByText("项已选择", { exact: false })).toBeTruthy();
    expect(
      fetcher.mock.calls.some(([path]) => path.includes("page=2&page_size=20")),
    ).toBe(true);
  });
  it("preserves batch account selection across state refresh and sends the real contract", async () => {
    const fetcher = vi.fn((path: string) =>
      Promise.resolve(
        json(
          path === "/api/auto-stock"
            ? {
                ok: true,
                config: {
                  enabled: false,
                  all_accounts: true,
                  target: 5,
                  batch: 1,
                },
              }
            : { ok: true, accepted: true },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    const { Wrapper } = wrapper();
    const view = render(
      <Wrapper>
        <Batch accounts={accounts} state={{}} refresh={() => {}} />
      </Wrapper>,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: /测试账号 A/ }));
    view.rerender(
      <Wrapper>
        <Batch
          accounts={[...accounts]}
          state={{ today_created: 1 }}
          refresh={() => {}}
        />
      </Wrapper>,
    );
    expect(
      (screen.getByRole("checkbox", { name: /测试账号 A/ }) as HTMLInputElement)
        .checked,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "开始创建" }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([path]) => path === "/api/create-batch"),
      ).toBe(true),
    );
    const request = (fetcher.mock.calls as any[]).find(
      ([path]) => path === "/api/create-batch",
    );
    expect(JSON.parse(request[1].body)).toEqual({
      account_ids: ["a"],
      count_per_account: 5,
      label: "",
      create_pickup_links: false,
    });
  });
});
