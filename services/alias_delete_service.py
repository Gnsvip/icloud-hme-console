"""Bounded background deletion with one fresh alias list per account."""
import concurrent.futures
import copy
import queue
import threading
import time
import uuid


class DeleteJobError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class AliasDeleteJobs:
    MAX_ITEMS = 200
    WORKERS = 2
    TTL = 1800

    def __init__(self, accounts, record_result):
        self.accounts = accounts
        self.record_result = record_result
        self.jobs = {}
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="alias-delete-job")

    def _snapshot(self, job):
        rows = job["items"]
        return {"ok": True, "job_id": job["id"], "state": job["state"],
                "total": len(rows), "completed": sum(r["state"] in ("deleted", "absent", "failed") for r in rows),
                "deleted": sum(r["state"] == "deleted" for r in rows),
                "absent": sum(r["state"] == "absent" for r in rows),
                "failed": sum(r["state"] == "failed" for r in rows),
                "items": copy.deepcopy(rows), "warning": job.get("warning", "")}

    def _cleanup(self):
        for key, job in list(self.jobs.items()):
            if job["state"] == "complete" and time.monotonic() - job["finished"] > self.TTL:
                del self.jobs[key]

    def start(self, data):
        if not isinstance(data, dict):
            raise DeleteJobError("请求格式不正确")
        key, items = data.get("request_id"), data.get("items")
        if not isinstance(key, str) or not 8 <= len(key) <= 100:
            raise DeleteJobError("缺少批次标识，请重新打开删除窗口。")
        if not isinstance(items, list) or not 1 <= len(items) <= self.MAX_ITEMS:
            raise DeleteJobError(f"每次请选择 1 至 {self.MAX_ITEMS} 个邮箱。")
        rows, seen = [], set()
        for item in items:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in ("email", "account_id")):
                raise DeleteJobError("邮箱缺少地址或所属账号，请先同步。")
            email = item["email"].strip().lower()
            acc_id = item["account_id"].strip()
            if not email or "@" not in email or len(email) > 254:
                raise DeleteJobError("邮箱地址无效，请刷新列表。")
            if not self.accounts.get_account(acc_id):
                raise DeleteJobError(f"{email}：所属账号不存在，请刷新列表或重新关联账号。")
            # Local/mail-cache records may not have an Apple ID. Resolve these
            # by exact email in this account's fresh cloud list before writing.
            alias_id = item.get("anonymousId")
            if alias_id is None:
                alias_id = ""
            if not isinstance(alias_id, str) or len(alias_id) > 512:
                raise DeleteJobError(f"{email}：云端标识格式无效，请先同步。")
            alias_id = alias_id.strip()
            if email in seen:
                raise DeleteJobError("同一邮箱不能重复出现在删除批次中。")
            seen.add(email)
            rows.append({"email": email, "account_id": acc_id, "anonymousId": alias_id, "state": "pending", "error": ""})
        with self.lock:
            self._cleanup()
            for job in self.jobs.values():
                if job["request_id"] == key:
                    if job["targets"] != [(r["account_id"], r["email"], r["anonymousId"]) for r in rows]:
                        raise DeleteJobError("批次标识已用于其他邮箱，请重新打开窗口。", 409)
                    return self._snapshot(job)
            if any(j["state"] != "complete" for j in self.jobs.values()):
                raise DeleteJobError("已有云端删除任务进行中，请先查看当前进度。", 409)
            if len(self.jobs) >= 20:
                self.jobs.pop(next(iter(self.jobs)))
            job = {"id": uuid.uuid4().hex, "request_id": key, "state": "preparing", "items": rows,
                   "targets": [(r["account_id"], r["email"], r["anonymousId"]) for r in rows]}
            self.jobs[job["id"]] = job
            self.pool.submit(self._run, job)
            return self._snapshot(job)

    def status(self, job_id):
        with self.lock:
            self._cleanup()
            if job_id not in self.jobs:
                raise DeleteJobError("删除任务已过期或服务已重启，请刷新云端列表核对结果。", 410)
            return self._snapshot(self.jobs[job_id])

    def active(self):
        with self.lock:
            job = next((j for j in self.jobs.values() if j["state"] != "complete"), None)
            return {"ok": True, "job": self._snapshot(job) if job else None}

    def _result(self, row, state, error="", result=None):
        # Serialize file/cache changes; network operations use separate sessions.
        with self.lock:
            if result:
                try:
                    self.record_result(row["account_id"], result)
                except Exception:
                    # A confirmed cloud deletion must never be replayed just
                    # because local persistence failed.
                    error = "云端结果已确认，本地状态保存失败，请同步云端列表。"
            row.update(state=state, error=error[:300])

    def _run(self, job):
        try:
            account_ids = dict.fromkeys(r["account_id"] for r in job["items"])
            for acc_id in account_ids:
                rows = [r for r in job["items"] if r["account_id"] == acc_id]
                self._account(job, acc_id, rows)
        except Exception as exc:
            for row in job["items"]:
                if row["state"] in ("pending", "deleting"):
                    self._result(row, "failed", str(exc))
        finally:
            with self.lock:
                job.update(state="complete", finished=time.monotonic())

    def _account(self, job, acc_id, rows):
        prepared = None
        try:
            prepared = self.accounts.get_client(acc_id, verbose=False)
            aliases = prepared.list_aliases(timeout=15, max_attempts=1)
            by_id = {a["anonymousId"]: a for a in aliases}
            by_email = {a["email"].lower(): a for a in aliases}
            pending = queue.Queue()
            for row in rows:
                current_id = by_id.get(row["anonymousId"]) if row["anonymousId"] else None
                if current_id and current_id["email"].lower() != row["email"]:
                    self._result(row, "failed", "邮箱地址与云端标识不一致，请先同步云端列表。")
                    continue
                alias = by_email.get(row["email"])
                if alias is None:
                    self._result(row, "absent", result={"email": row["email"], "deleted": False, "already_absent": True})
                elif not alias.get("anonymousId"):
                    self._result(row, "failed", "云端标识缺失，请先同步列表。")
                else:
                    pending.put((row, alias))
            with self.lock:
                job["state"] = "deleting"
            limited = threading.Event()

            def worker():
                client = self.accounts.get_client(acc_id, verbose=False)
                try:
                    client._service_url = prepared._service_url
                    client.session.cookies.update(prepared.session.cookies)
                    while True:
                        try:
                            row, alias = pending.get_nowait()
                        except queue.Empty:
                            return
                        if limited.is_set():
                            self._result(row, "failed", "Apple 暂时限制请求，尚未执行，请稍后重试。")
                            continue
                        with self.lock:
                            row["state"] = "deleting"
                        try:
                            if client.delete(alias["anonymousId"], active=alias["active"]) is not True:
                                raise RuntimeError("Apple 未确认删除，记录已保留。")
                            self._result(row, "deleted", result={"email": row["email"], "deleted": True, "already_absent": False})
                        except Exception as exc:
                            detail = str(exc)
                            if any(t in detail.lower() for t in ("429", "too many", "rate limit", "http 401", "http 403")):
                                limited.set()
                            self._result(row, "failed", detail)
                finally:
                    client.session.close()

            if not pending.empty():
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.WORKERS, thread_name_prefix="alias-delete") as pool:
                    futures = [pool.submit(worker) for _ in range(min(self.WORKERS, pending.qsize()))]
                    for future in futures:
                        future.result()
            with self.lock:
                job["state"] = "syncing"
            # Refresh counts once per account, using the existing connection.
            try:
                current = prepared.list_aliases(timeout=15, max_attempts=1)
                self.accounts.update_account(acc_id, alias_total=len(current), alias_active=sum(bool(a["active"]) for a in current))
            except Exception:
                with self.lock:
                    job["warning"] = "删除结果已保存，账号数量刷新失败，可稍后同步。"
        except Exception as exc:
            for row in rows:
                if row["state"] in ("pending", "deleting"):
                    self._result(row, "failed", str(exc))
        finally:
            if prepared:
                prepared.session.close()

    def shutdown(self):
        self.pool.shutdown(wait=True)
