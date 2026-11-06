import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppleLoginForm } from "./pages/AppleLogin";
import { AccountForm } from "./pages/Accounts";

const flow = { ok: true, flow_id: "synthetic-flow", state: "awaiting_code", delivery: "trusted_device" };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json" },
});
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  fetcher = vi.fn().mockResolvedValue(json(flow));
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function signIn() {
  fireEvent.change(screen.getByLabelText("Apple 账号"), { target: { value: "demo@example.test" } });
  fireEvent.change(screen.getByLabelText(/Apple 登录密码/), { target: { value: "synthetic-password" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "登录 Apple" })); });
}
async function verify() {
  fireEvent.change(screen.getByLabelText("六位验证码"), { target: { value: "123456" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "验证并连接" })); });
}
async function poll() { await act(async () => { await vi.advanceTimersByTimeAsync(1500); }); }

describe("Apple login", () => {
  it("defaults to account login and keeps Cookie import as a fallback", () => {
    render(<AccountForm close={vi.fn()} done={vi.fn()} />);
    expect(screen.getByLabelText("Apple 账号")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "改用 Cookie 导入" }));
    expect(screen.getByRole("button", { name: "使用账号密码登录" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "登录 Apple" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "使用账号密码登录" }));
    expect(screen.getByLabelText("Apple 账号")).toBeTruthy();
  });

  it("submits password then code, polls completion and includes the selected account", async () => {
    const done = vi.fn();
    render(<AppleLoginForm close={vi.fn()} done={done} account={{ id: "selected", host: "icloud.com.cn" }} />);
    await signIn();
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({
      apple_id: "demo@example.test", password: "synthetic-password", host: "icloud.com.cn", account_id: "selected",
    });
    expect(screen.queryByLabelText(/Apple 登录密码/)).toBeNull();
    fetcher.mockResolvedValueOnce(json({ ...flow, state: "verifying" }));
    await verify();
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ code: "123456" });
    expect(screen.getByRole("status").textContent).toContain("正在验证");
    fetcher.mockResolvedValueOnce(json({ ...flow, state: "complete", account: { status: "active" } }));
    await poll();
    expect(done).toHaveBeenCalledTimes(1);
    await poll();
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("shows SMS guidance and allows retrying an incorrect code", async () => {
    fetcher.mockResolvedValueOnce(json({ ...flow, delivery: "sms" }));
    render(<AppleLoginForm close={vi.fn()} done={vi.fn()} />);
    await signIn();
    expect(screen.getByText(/受信任手机号的短信验证码/)).toBeTruthy();
    fetcher.mockResolvedValueOnce(json({ ...flow, error: "验证码未通过" }));
    await verify();
    expect(screen.getByRole("alert").textContent).toContain("验证码未通过");
    expect((screen.getByLabelText("六位验证码") as HTMLInputElement).value).toBe("");
  });

  it("keeps an editable code field when automatic delivery is unavailable", async () => {
    const manual = { ...flow, delivery: "trusted_device_manual" };
    fetcher.mockResolvedValueOnce(json({ ...manual, state: "starting" }));
    render(<AppleLoginForm close={vi.fn()} done={vi.fn()} />);
    await signIn();
    fetcher.mockResolvedValueOnce(json(manual));
    await poll();
    expect(screen.getByText(/设备上已经显示的六位验证码/)).toBeTruthy();
    expect((screen.getByLabelText("六位验证码") as HTMLInputElement).disabled).toBe(false);
    fetcher.mockResolvedValueOnce(json({ ...manual, error: "验证码未通过" }));
    await verify();
    expect(JSON.parse(fetcher.mock.calls.at(-1)?.[1].body)).toEqual({ code: "123456" });
    expect(screen.getByRole("alert").textContent).toContain("验证码未通过");
    expect((screen.getByLabelText("六位验证码") as HTMLInputElement).disabled).toBe(false);
  });

  it("stops polling an expired flow and can restart", async () => {
    render(<AppleLoginForm close={vi.fn()} done={vi.fn()} />);
    await signIn();
    fetcher.mockResolvedValueOnce(json({ ok: false, error: "登录已过期" }, 410));
    await poll();
    expect(screen.getByRole("alert").textContent).toContain("登录已过期");
    const calls = fetcher.mock.calls.length;
    await poll();
    expect(fetcher.mock.calls).toHaveLength(calls);
    fireEvent.click(screen.getByRole("button", { name: "重新登录" }));
    expect(screen.getByLabelText("Apple 账号")).toBeTruthy();
    expect((screen.getByLabelText(/Apple 登录密码/) as HTMLInputElement).value).toBe("");
  });

  it("clears the password and shows a failed start without opening a code form", async () => {
    fetcher.mockResolvedValueOnce(json({ ok: false, error: "请稍后重试" }, 429));
    render(<AppleLoginForm close={vi.fn()} done={vi.fn()} />);
    await signIn();
    expect(screen.getByRole("alert").textContent).toContain("请稍后重试");
    expect((screen.getByLabelText(/Apple 登录密码/) as HTMLInputElement).value).toBe("");
    expect(screen.queryByLabelText("六位验证码")).toBeNull();
  });

  it("cancels a flow returned after its dialog was closed", async () => {
    let resolve!: (response: Response) => void;
    fetcher.mockReturnValueOnce(new Promise<Response>((r) => { resolve = r; }));
    const done = vi.fn();
    const view = render(<AppleLoginForm close={vi.fn()} done={done} />);
    await signIn();
    view.unmount();
    await act(async () => { resolve(json(flow)); });
    expect(fetcher.mock.calls.at(-1)?.[1].method).toBe("DELETE");
    expect(done).not.toHaveBeenCalled();
  });

  it("does not poll during verification or complete a closed dialog", async () => {
    const done = vi.fn();
    const view = render(<AppleLoginForm close={vi.fn()} done={done} />);
    await signIn();
    let resolve!: (response: Response) => void;
    fetcher.mockReturnValueOnce(new Promise<Response>((r) => { resolve = r; }));
    await verify();
    const calls = fetcher.mock.calls.length;
    await poll();
    expect(fetcher.mock.calls).toHaveLength(calls);
    view.unmount();
    await act(async () => { resolve(json({ ...flow, state: "complete" })); });
    expect(fetcher.mock.calls.at(-1)?.[1].method).toBe("DELETE");
    expect(done).not.toHaveBeenCalled();
  });
});
