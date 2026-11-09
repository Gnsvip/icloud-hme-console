import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountBenefits, appleFamilyInvitation } from "./pages/AccountBenefits";

afterEach(() => vi.unstubAllGlobals());
const account = { id: "acc_demo", name: "测试账号", real_email: "demo@example.test", host: "icloud.com.cn" };
const state = { ok: true, host: "icloud.com.cn", checked_at: "2026-11-10T03:00:00Z", hide_my_email: true,
  family: { ok: true, is_member: true, is_organizer: false, invitation_count: 0,
    members: [{ name: "本人", apple_id: "demo@example.test", is_self: true, is_organizer: false }] },
  subscription: { ok: true, included: true, sources: ["家庭共享"] },
  storage: { ok: true, total_bytes: 200 * 1024 ** 3, used_bytes: 1024 ** 3 } };
function renderBenefits() {
  return render(<QueryClientProvider client={new QueryClient()}><AccountBenefits account={account} close={vi.fn()} /></QueryClientProvider>);
}
const response = (value: any, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });

describe("family and iCloud+", () => {
  it("shows live source and keeps Apple checkout in the account region without mutation", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(state));
    vi.stubGlobal("fetch", fetcher);
    renderBenefits();
    expect(await screen.findByText("已加入 · 1 人")).toBeTruthy();
    expect(screen.getByText("200 GB")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "开通或升级 iCloud+" }));
    expect(screen.getByRole("link", { name: /前往 Apple 开通/ }).getAttribute("href")).toBe("https://www.icloud.com.cn/plan/");
    expect(screen.getByText(/此账号已通过家庭共享/)).toBeTruthy();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].method).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "刷新状态" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  });

  it("distinguishes a failed family lookup from not being in a family", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...state, family: { ok: false, error: "家庭接口暂时不可用" } })));
    renderBenefits();
    expect(await screen.findByText("家庭接口暂时不可用")).toBeTruthy();
    expect(screen.queryByText("尚未加入家庭")).toBeNull();
    expect(screen.getByText("200 GB")).toBeTruthy();
  });

  it("keeps official help available after an expired Apple session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ok: false, error: "请重新登录此账号" }, 502)));
    renderBenefits();
    expect(await screen.findByText("请重新登录此账号")).toBeTruthy();
    expect(screen.getByRole("link", { name: "查看加入家庭步骤" })).toBeTruthy();
    expect(screen.queryByText("未检测到付费方案")).toBeNull();
  });

  it("rejects arbitrary links and only opens the entered Apple invitation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(state)));
    renderBenefits();
    await screen.findByText("200 GB");
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "https://evil.test/family" } });
    expect(screen.queryByRole("link", { name: "在 Apple 打开邀请" })).toBeNull();
    const url = "https://setup.icloud.com/family/messages?aaaction=showFamilyInvite&inviteCode=synthetic";
    fireEvent.change(input, { target: { value: url } });
    expect(screen.getByRole("link", { name: "在 Apple 打开邀请" }).getAttribute("href")).toBe(url);
  });
});

it.each([
  "javascript:alert(1)", "https://setup.icloud.com.evil.test/family/messages?aaaction=showFamilyInvite&inviteCode=x",
  "https://setup.icloud.com@evil.test/family/messages?aaaction=showFamilyInvite&inviteCode=x",
  "https://setup.icloud.com/family/messages?aaaction=showFamilyInvite&inviteCode=organizer_create",
  "https://setup.icloud.com/family/messages?aaaction=showFamilyInvite", "http://setup.icloud.com/family/messages?aaaction=showFamilyInvite&inviteCode=x",
])("rejects unsupported invitation %s", (url) => expect(appleFamilyInvitation(url)).toBeNull());
