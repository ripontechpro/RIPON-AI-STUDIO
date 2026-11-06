"""Shared task management for every slow operation (AI, batch, document cleanup). Qt-free; the UI listens via callbacks."""
import threading, time, traceback

class Cancelled(Exception): pass

class CancelToken:
    def __init__(self): self._e = threading.Event()
    def cancel(self): self._e.set()
    @property
    def cancelled(self): return self._e.is_set()
    def check(self):
        if self._e.is_set(): raise Cancelled()

class TaskContext:
    """Passed to the worker function: report progress, check for cancel."""
    def __init__(self, task): self._t = task; self.token = task.token
    def progress(self, frac, msg=""):
        self.token.check(); self._t._set_progress(frac, msg)
    def check(self): self.token.check()

class Task:
    def __init__(self, title, fn, on_progress=None, on_done=None, on_error=None, tag=None):
        self.title, self.fn, self.tag = title, fn, tag
        self.token = CancelToken()
        self.state = "queued"          # queued running done error cancelled
        self.frac, self.msg, self.result, self.error = 0.0, "", None, None
        self._cb = (on_progress, on_done, on_error)
    def cancel(self): self.token.cancel()
    def _set_progress(self, frac, msg):
        self.frac, self.msg = max(0.0, min(1.0, float(frac))), msg
        if self._cb[0]: self._cb[0](self)

class TaskManager:
    """One worker thread per task; at most `max_parallel` run at once (AI models are heavy). Callbacks (all receive the Task) run on the worker thread:
    the Qt layer re-emits them as signals so the GUI thread is never touched from here."""
    def __init__(self, max_parallel=1):
        self._sem = threading.Semaphore(max_parallel); self.tasks = []; self._lock = threading.Lock()
    def submit(self, title, fn, on_progress=None, on_done=None, on_error=None, tag=None):
        t = Task(title, fn, on_progress, on_done, on_error, tag)
        with self._lock: self.tasks.append(t)
        threading.Thread(target=self._run, args=(t,), daemon=True).start()
        return t
    def _run(self, t):
        with self._sem:
            if t.token.cancelled:
                t.state = "cancelled"; self._fire(t, 2, Cancelled()); return
            t.state = "running"
            try:
                t.result = t.fn(TaskContext(t))
                t.state = "done"; self._fire(t, 1, t)
            except Cancelled:
                t.state = "cancelled"; self._fire(t, 2, Cancelled())
            except Exception as e:                                 # never let a worker crash the app
                t.state = "error"; t.error = e; t.tb = traceback.format_exc(); self._fire(t, 2, e)
    @staticmethod
    def _fire(t, idx, arg):
        cb = t._cb[idx]
        if cb:
            try: cb(t)                                              # every callback receives the Task (t.result / t.error / t.state)
            except Exception: pass
    def wait(self, t, timeout=30):
        end = time.time() + timeout
        while t.state in ("queued", "running") and time.time() < end: time.sleep(0.01)
        return t.state
