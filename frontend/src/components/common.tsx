import { useState, type ReactNode } from "react";
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Inbox,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import type { Row } from "@/lib/api";
export { Button };
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Empty({
  title = "暂无数据",
  detail = "有新的记录时会显示在这里",
  action,
}: {
  title?: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Inbox size={23} />
      </div>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div className="skeleton-group" aria-label="正在加载">
      {[1, 2, 3, 4].map((i) => (
        <div className="skeleton" key={i} />
      ))}
    </div>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: any;
  retry?: () => any;
}) {
  return error ? (
    <div className="error-notice" role="alert">
      <AlertCircle size={16} />
      <span>{error.message || String(error)}</span>
      {retry && <button onClick={retry}>重试</button>}
    </div>
  ) : null;
}
export function RefreshButton({
  busy,
  onClick,
}: {
  busy?: boolean;
  onClick: () => any;
}) {
  return (
    <Button variant="outline" size="sm" onClick={onClick} disabled={busy}>
      <RefreshCw className={busy ? "spin" : ""} />
      刷新
    </Button>
  );
}
export function SearchBox({
  value,
  onChange,
  placeholder = "搜索邮箱、标签或备注…",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="search-field">
      <Search size={16} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value && (
        <button aria-label="清除搜索" onClick={() => onChange("")}>
          ×
        </button>
      )}
    </div>
  );
}
export function AccountSelect({
  accounts,
  value,
  onChange,
}: {
  accounts: Row[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select
      aria-label="筛选账号"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">全部账号</option>
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>
          {a.name || a.icloud_email || a.id}
        </option>
      ))}
    </select>
  );
}
export function Pager({
  page,
  pages,
  total,
  onPage,
  size,
  onSize,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (n: number) => void;
  size?: number;
  onSize?: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        共 <strong>{total.toLocaleString()}</strong> 条记录
      </span>
      <div>
        {onSize && (
          <select
            aria-label="每页条数"
            value={size}
            onChange={(e) => onSize(Number(e.target.value))}
          >
            {[20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n} 条 / 页
              </option>
            ))}
          </select>
        )}
        <span>
          {page} / {pages || 1}
        </span>
        <Button
          variant="outline"
          size="icon"
          aria-label="上一页"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="下一页"
          disabled={page >= (pages || 1)}
          onClick={() => onPage(page + 1)}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
export function Pill({ value }: { value: string }) {
  const label: Row = {
    active: "正常",
    warning: "待确认",
    error: "需处理",
    unused: "未使用",
    finished: "已使用",
    trash: "垃圾箱",
    disabled: "已停用",
  };
  return (
    <span className={`pill pill-${value}`}>
      <i />
      {label[value] || value || "未检查"}
    </span>
  );
}
export function Modal({
  title,
  description,
  children,
  close,
  wide = false,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className={wide ? "modal-wide" : ""}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description || "填写信息后保存。"}
          </DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}
export function Confirm({
  title,
  description,
  onConfirm,
  close,
}: {
  title: string;
  description: string;
  onConfirm: () => Promise<any>;
  close: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal
      title={title}
      description={description}
      close={() => !busy && close()}
    >
      <ErrorNotice error={error} />
      <DialogFooter>
        <Button variant="outline" onClick={close} disabled={busy}>
          取消
        </Button>
        <Button
          variant="destructive"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              close();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy && <Loader2 className="spin" />}确认操作
        </Button>
      </DialogFooter>
    </Modal>
  );
}
export function CopyButton({
  value,
  label,
}: {
  value: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size={label ? "sm" : "icon"}
      aria-label={label || "复制"}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          toast.error("复制失败，请手动选择文本复制");
        }
      }}
    >
      {copied ? <Check /> : <Copy />}
      {label}
    </Button>
  );
}
export function Submit({
  busy,
  disabled = false,
  children = "保存",
}: {
  busy: boolean;
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <Button type="submit" disabled={busy || disabled}>
      {busy && <Loader2 className="spin" />}
      {children}
    </Button>
  );
}
