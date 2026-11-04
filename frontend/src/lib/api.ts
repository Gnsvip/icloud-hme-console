import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
export type Row = Record<string, any>;
export async function api(
  path: string,
  options: RequestInit & { timeout?: number } = {},
): Promise<Row> {
  const { timeout = 60000, signal, ...rest } = options;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch(path, {
      ...rest,
      signal: controller.signal,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...rest.headers },
    });
    if (response.status === 401) {
      window.dispatchEvent(new Event("hme-session-expired"));
      throw new Error("登录已过期，请重新登录");
    }
    if (!response.headers.get("content-type")?.includes("application/json"))
      throw new Error("服务暂时不可用，请稍后重试");
    const data = await response.json();
    if (!response.ok || data.ok === false)
      throw Object.assign(new Error(
        (data.saved ? "已保存，但连接测试失败：" : "") +
          (data.error || data.errors?.join("；") || "操作未完成，请重试"),
      ), { status: response.status });
    return data;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("请求已取消或超时，请重试");
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
export const post = (path: string, body: Row = {}, timeout = 120000) =>
  api(path, { method: "POST", body: JSON.stringify(body), timeout });
export const enc = encodeURIComponent;
export function useVisible() {
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}
export function useRemote(
  path: string,
  enabled = true,
  poll = 0,
  refreshOnFocus = true,
) {
  const visible = useVisible();
  return useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => api(path, { signal }),
    enabled,
    staleTime: 15000,
    retry: 1,
    refetchInterval: visible && poll ? poll : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: enabled && refreshOnFocus,
    placeholderData: keepPreviousData,
  });
}
export function useDebounced(value: string, delay = 250) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
export function stamp(value: any) {
  if (!value) return "—";
  const date = new Date(
    typeof value === "number" && value < 1e12 ? value * 1000 : value,
  );
  return isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
}
export function download(text: string, name: string) {
  const url = URL.createObjectURL(
    new Blob(["\ufeff", text], { type: "text/plain;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
