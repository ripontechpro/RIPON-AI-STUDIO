"""Runs engine tasks on worker threads and delivers their callbacks on the GUI thread (Qt queued signals)."""
from PySide6.QtCore import QObject, Signal
from ..engine.tasks import TaskManager

class TaskBridge(QObject):
    started = Signal(object)
    progress = Signal(object)
    finished = Signal(object)          # every task, whatever its outcome

    def __init__(self, parent=None):
        super().__init__(parent); self.tm = TaskManager(max_parallel=1)
        self.finished.connect(self._dispatch)

    def run(self, title, fn, done=None, fail=None, quiet=False):
        """fn(ctx) runs off-thread. done(result) / fail(exception) run on the GUI thread. quiet=True hides it from the status bar."""
        tag = dict(done=done, fail=fail, quiet=quiet)
        t = self.tm.submit(title, fn, on_progress=lambda t: self.progress.emit(t), on_done=lambda t: self.finished.emit(t),
                           on_error=lambda t: self.finished.emit(t), tag=tag)
        self.started.emit(t); return t

    def _dispatch(self, t):
        tag = t.tag or {}
        if t.state == "done" and tag.get("done"): tag["done"](t.result)
        elif t.state == "error" and tag.get("fail"): tag["fail"](t.error)
