"""Bounded mail jobs with a shared deadline and socket cancellation."""
import concurrent.futures
import imaplib
import socket
import threading
import time

_local = threading.local()


class MailDeadline:
    def __init__(self, timeout):
        self.expires = time.monotonic() + timeout
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._sockets = []

    def remaining(self):
        seconds = self.expires - time.monotonic()
        if self.cancelled.is_set() or seconds <= 0:
            raise TimeoutError("IMAP 请求超时，请稍后重试")
        return seconds

    def watch(self, sock):
        with self._lock:
            self._sockets.append(sock)
            cancelled = self.cancelled.is_set()
        if cancelled:
            self._close(sock)
        self.remaining()

    @staticmethod
    def _close(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def cancel(self):
        self.cancelled.set()
        self.close_connections()

    def close_connections(self):
        with self._lock:
            sockets = list(self._sockets)
        for sock in sockets:
            self._close(sock)


class MailExecutor:
    def __init__(self, max_workers, max_pending, name):
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
        self._slots = threading.BoundedSemaphore(max_workers + max_pending)

    def submit(self, fn, timeout=35):
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("邮件查询繁忙，等待中的任务已满，请稍后重试")
        budget = MailDeadline(timeout)
        future = concurrent.futures.Future()
        future.mail_deadline = budget

        def run():
            if not future.set_running_or_notify_cancel():
                self._slots.release()
                return
            previous = getattr(_local, "budget", None)
            _local.budget = budget
            timer = None
            error = None
            result = None
            try:
                timer = threading.Timer(budget.remaining(), budget.cancel)
                timer.daemon = True
                timer.start()
                result = fn()
                budget.remaining()
            except BaseException as exc:
                error = exc
            finally:
                if timer is not None:
                    timer.cancel()
                budget.close_connections()
                _local.budget = previous
                self._slots.release()
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        try:
            self._pool.submit(run)
        except BaseException:
            self._slots.release()
            raise
        return future

    def shutdown(self, wait=True):
        self._pool.shutdown(wait=wait)


def wait_for_mail(future):
    try:
        if future.done():
            return future.result()
        return future.result(timeout=future.mail_deadline.remaining())
    except (TimeoutError, concurrent.futures.TimeoutError):
        future.mail_deadline.cancel()
        future.cancel()
        raise TimeoutError("IMAP 请求超时，请确认邮箱连接正常后重试") from None


def open_imap(host, port=993, *, secure=True, ssl_context=None, timeout=20):
    budget = getattr(_local, "budget", None) or MailDeadline(60)
    options = {"timeout": min(timeout, budget.remaining())}
    if secure:
        if ssl_context is not None:
            options["ssl_context"] = ssl_context
        conn = imaplib.IMAP4_SSL(host, port, **options)
    else:
        conn = imaplib.IMAP4(host, port, **options)
    try:
        budget.watch(conn.sock)
        command = conn._command

        def guarded_command(*args, **kwargs):
            conn.sock.settimeout(min(timeout, budget.remaining()))
            return command(*args, **kwargs)

        conn._command = guarded_command
        return conn
    except BaseException:
        MailDeadline._close(conn.sock)
        raise


def close_imap(conn):
    if conn is None:
        return
    try:
        conn.logout()
    except Exception:
        pass
    finally:
        try:
            conn.shutdown()
        except Exception:
            pass
