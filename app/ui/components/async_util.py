"""Run blocking work (network probes, Bale calls) off the GUI thread and get the result back on it."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object, object)       # result, exception


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], sig: _Signals):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self) -> None:
        try:
            self.sig.done.emit(self.fn(), None)
        except BaseException as e:  # noqa: BLE001 - surfaced to the callback
            self.sig.done.emit(None, e)


_live: set = set()


def run_async(fn: Callable[[], Any], callback: Callable[[Any, BaseException | None], None]) -> None:
    sig = _Signals()
    _live.add(sig)

    def _done(res, err):
        _live.discard(sig)
        callback(res, err)

    sig.done.connect(_done)
    QThreadPool.globalInstance().start(_Task(fn, sig))
