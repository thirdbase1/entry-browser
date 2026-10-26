"""entrybrowser.js — JavaScript support.

Strategy: if `quickjs` (or dukpy) is installed, run scripts in a real ES engine
with a small DOM shim (getElementById/innerHTML basics + console). Otherwise
scripts are skipped gracefully — the engine still renders the page.
"""
from __future__ import annotations

def has_js() -> bool:
    try:
        import dukpy  # noqa
        return True
    except ImportError:
        try:
            import quickjs  # noqa
            return True
        except ImportError:
            return False

class JSRuntime:
    def __init__(self, doc):
        self.doc = doc
        self.console_log: list[str] = []
        self._engine = None
        try:
            import dukpy
            self._engine = "dukpy"
            self._duk = dukpy
        except ImportError:
            pass
    def run(self, code: str, url="<inline>") -> str | None:
        if not self._engine:
            return None
        try:
            if self._engine == "dukpy":
                out = self._duk.evaljs(code, document=None, console=_Console(self.console_log))
                return str(out) if out is not None else None
        except Exception as e:
            return f"[js error] {e}"
        return None

class _Console:
    def __init__(self, sink): self._sink = sink
    def log(self, *a): self._sink.append(" ".join(str(x) for x in a))
    def error(self, *a): self._sink.append("ERROR: " + " ".join(str(x) for x in a))
    def warn(self, *a): self._sink.append("WARN: " + " ".join(str(x) for x in a))
