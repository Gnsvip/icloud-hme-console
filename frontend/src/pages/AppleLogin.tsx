import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, enc, post, type Row } from "@/lib/api";
import { Button, ErrorNotice, Field, Modal, Submit } from "@/components/common";

const progress: Record<string, string> = {
  starting: "正在连接 Apple，请留意受信任设备上的登录提示…",
  verifying: "正在验证验证码…",
  importing: "登录成功，正在连接邮箱工作台…",
};
const codeGuidance: Record<string, string> = {
  sms: "请输入 Apple 发到受信任手机号的短信验证码。",
  trusted_device: "请在受信任的 Apple 设备上允许这次登录，再输入六位验证码。",
  trusted_device_manual: "请输入受信任 Apple 设备上已经显示的六位验证码。请使用当前这次登录的验证码。",
};

export function AppleLoginForm({ close, done, useCookie, account }: {
  close: () => void;
  done: () => void;
  useCookie?: () => void;
  account?: Row;
}) {
  const [flow, setFlow] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<any>(null);
  const flowId = useRef("");
  const mounted = useRef(true);
  const completed = useRef(false);
  const [startingAppleId, setStartingAppleId] = useState("");

  const discard = (id: string) => {
    if (id) void api(`/api/apple-login/${enc(id)}`, { method: "DELETE" }).catch(() => {});
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      discard(flowId.current);
    };
  }, []);

  useEffect(() => {
    if (busy || !flow || flow.state === "failed" || flow.state === "complete") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api(`/api/apple-login/${enc(flow.flow_id)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setFlow(next);
        setError(null);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err);
        if (err.status === 410) setFlow({ ...flow, state: "failed" });
        else timer = setTimeout(poll, 3000);
      }
    };
    timer = setTimeout(poll, 1500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [flow, busy]);

  useEffect(() => {
    if (flow?.state === "complete" && !completed.current) {
      completed.current = true;
      if (flow.account?.status === "warning") toast.warning(flow.account.last_error);
      else toast.success("Apple 登录成功，账号已连接");
      done();
    }
  }, [flow, done]);

  const restart = () => {
    discard(flowId.current);
    flowId.current = "";
    setFlow(null);
    setError(null);
    completed.current = false;
  };
  return (
    <Modal title="登录 Apple 账号" description="输入账号、登录密码和验证码，直接连接 iCloud，无需浏览器插件。" close={close}>
      {!flow ? (
        <form className="form-stack" onSubmit={async (e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const body = Object.fromEntries(new FormData(form)) as Row;
          if (account) body.account_id = account.id;
          setBusy(true); setError(null);
          setStartingAppleId(String(body.apple_id || ""));
          try {
            const next = await post("/api/apple-login", body);
            if (!mounted.current) { discard(next.flow_id); return; }
            flowId.current = next.flow_id;
            setFlow(next);
          } catch (err) {
            if (mounted.current) setError(err);
          } finally {
            const password = form.elements.namedItem("password") as HTMLInputElement | null;
            if (password) password.value = "";
            if (mounted.current) setBusy(false);
          }
        }}>
          <div className="form-grid">
            <Field label="账号名称"><input name="name" defaultValue={account?.name || ""} placeholder="可选，例如：个人账号" disabled={busy} /></Field>
            <Field label="账号区域"><select name="host" defaultValue={account?.host || "icloud.com"} disabled={busy}>
              <option value="icloud.com">国际区 iCloud</option><option value="icloud.com.cn">中国区 iCloud</option>
            </select></Field>
          </div>
          <Field label="Apple 账号"><input name="apple_id" autoComplete="username" defaultValue={startingAppleId || account?.real_email || ""} required disabled={busy} placeholder="邮箱地址或手机号" /></Field>
          <Field label="Apple 登录密码" hint="填写 Apple 账号密码；收件使用的 App 专用密码可以在登录后单独配置。">
            <input name="password" type="password" autoComplete="current-password" required disabled={busy} />
          </Field>
          <ErrorNotice error={error} />
          <div className="form-actions">
            {useCookie && <Button type="button" variant="ghost" disabled={busy} onClick={useCookie}>改用 Cookie 导入</Button>}
            <Submit busy={busy}>登录 Apple</Submit>
          </div>
        </form>
      ) : (
        <div className="form-stack">
          {progress[flow.state] && <p role="status">{progress[flow.state]}</p>}
          {flow.state === "awaiting_code" && (
            <form className="form-stack" onSubmit={async (e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const code = String(new FormData(form).get("code") || "");
              setBusy(true); setError(null);
              try {
                const next = await post(`/api/apple-login/${enc(flow.flow_id)}/verify`, { code });
                if (mounted.current && flowId.current === next.flow_id) { setFlow(next); form.reset(); }
              }
              catch (err) { if (mounted.current) setError(err); }
              finally { if (mounted.current) setBusy(false); }
            }}>
              <p>{codeGuidance[flow.delivery] || codeGuidance.trusted_device}</p>
              <Field label="六位验证码"><input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required autoFocus disabled={busy} /></Field>
              <Submit busy={busy}>验证并连接</Submit>
            </form>
          )}
          <ErrorNotice error={error || flow.error} />
          <div className="form-actions">
            <Button variant="outline" disabled={busy} onClick={restart}>重新登录</Button>
            <Button variant="ghost" onClick={close}>取消登录</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
