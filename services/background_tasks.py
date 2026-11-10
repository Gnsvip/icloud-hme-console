"""Bounded admin jobs; accepted work is independent of the browser connection."""
import concurrent.futures
import copy
import hashlib
import json
import threading
import time

from services.alias_delete_service import DeleteJobError


class BackgroundTasks:
    TTL = 1800
    MAX_ACTIVE = 8

    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = {}
        # Serialize maintenance operations to avoid overlapping cloud scans/edits.
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="console-task")

    def _cleanup(self):
        for key, job in list(self.jobs.items()):
            if job["state"] == "complete" and time.monotonic() - job["finished"] > self.TTL:
                del self.jobs[key]

    def _snapshot(self, job):
        rows = job["items"]
        return {"ok": True, "job_id": job["id"], "title": job["title"], "state": job["state"],
                "total": len(rows), "completed": sum(r["state"] in ("complete", "failed") for r in rows),
                "failed": sum(r["state"] == "failed" for r in rows), "items": copy.deepcopy(rows)}

    def start(self, data, prepare):
        if not isinstance(data, dict):
            raise DeleteJobError("任务格式无效")
        key, title, steps = data.get("request_id"), data.get("title"), data.get("steps")
        if not isinstance(key, str) or not 8 <= len(key) <= 100 or not key.replace("-", "").isalnum():
            raise DeleteJobError("缺少有效的任务标识")
        if not isinstance(title, str) or not 1 <= len(title) <= 80:
            raise DeleteJobError("任务名称无效")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 500:
            raise DeleteJobError("每次请选择 1 至 500 项")
        encoded = json.dumps(steps, sort_keys=True, ensure_ascii=False).encode()
        if len(encoded) > 512000:
            raise DeleteJobError("任务内容过大")
        fingerprint = hashlib.sha256(encoded).hexdigest()
        # Validate the whole batch before accepting any side effect.
        execute, labels = prepare(steps)
        with self.lock:
            self._cleanup()
            existing = next((j for j in self.jobs.values() if key in j["request_ids"]), None)
            if existing:
                job = existing
                if job["fingerprint"] != fingerprint:
                    raise DeleteJobError("任务标识已用于其他操作", 409)
                return self._snapshot(job)
            for job in self.jobs.values():
                if job["state"] != "complete" and job["fingerprint"] == fingerprint:
                    if len(job["request_ids"]) >= 100:
                        raise DeleteJobError("相同任务重复提交过多，请查看当前任务", 409)
                    job["request_ids"].add(key)
                    return self._snapshot(job)
            if sum(j["state"] != "complete" for j in self.jobs.values()) >= self.MAX_ACTIVE:
                raise DeleteJobError("后台任务已满，请稍后再提交", 409)
            if len(self.jobs) >= 50:
                oldest = next((k for k, j in self.jobs.items() if j["state"] == "complete"), None)
                if oldest:
                    del self.jobs[oldest]
            job = {"id": key, "request_ids": {key}, "title": title, "fingerprint": fingerprint, "state": "queued",
                   "items": [{"label": label, "state": "pending", "error": ""} for label in labels]}
            self.jobs[key] = job
            self.pool.submit(self._run, job, execute)
            return self._snapshot(job)

    def _run(self, job, execute):
        def progress(index, result):
            with self.lock:
                job["items"][index].update(result)
        with self.lock:
            job["state"] = "running"
        try:
            execute(progress)
        except Exception:
            with self.lock:
                for row in job["items"]:
                    if row["state"] not in ("complete", "failed"):
                        row.update(state="failed", error="操作未完成，请刷新数据核对后重试。")
        finally:
            with self.lock:
                job.update(state="complete", finished=time.monotonic())

    def status(self, key):
        with self.lock:
            self._cleanup()
            job = next((j for j in self.jobs.values() if key in j["request_ids"]), None)
            if not job:
                raise DeleteJobError("任务记录已过期或服务已重启，请刷新数据核对结果。", 410)
            return self._snapshot(job)

    def active(self):
        with self.lock:
            return {"ok": True, "jobs": [self._snapshot(j) for j in self.jobs.values() if j["state"] != "complete"]}

    def shutdown(self):
        self.pool.shutdown(wait=True)
