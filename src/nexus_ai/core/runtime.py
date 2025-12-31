from __future__ import annotations

import os
import sys
from typing import TextIO

_FILTER_INSTALLED = False
_LITELLM_SPAM = "Provider List: https://docs.litellm.ai/docs/providers"


def ensure_litellm_quiet() -> None:
    # Default to quieter logging unless user explicitly sets it.
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    _install_litellm_filter()


class _FilteredStream:
    def __init__(self, stream: TextIO, blocked: str):
        self._stream = stream
        self._blocked = blocked
        self._buffer = ""

    def write(self, s):  # type: ignore[override]
        if not s:
            return 0
        text = s.decode("utf-8", errors="ignore") if isinstance(s, (bytes, bytearray)) else str(s)
        self._buffer += text
        lines = self._buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            self._buffer = lines[-1]
            lines = lines[:-1]
        else:
            self._buffer = ""

        out = []
        for line in lines:
            if self._blocked in line:
                continue
            out.append(line)
        if not out:
            return 0
        payload = "".join(out)
        try:
            return self._stream.write(payload)
        except TypeError:
            buf = getattr(self._stream, "buffer", None)
            if buf is not None:
                return buf.write(payload.encode("utf-8", errors="ignore"))
            return self._stream.write(payload)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return getattr(self._stream, "isatty", lambda: False)()

    def fileno(self) -> int:
        return self._stream.fileno()


def _install_litellm_filter() -> None:
    global _FILTER_INSTALLED
    if _FILTER_INSTALLED:
        return
    _FILTER_INSTALLED = True
    sys.stdout = _FilteredStream(sys.stdout, _LITELLM_SPAM)  # type: ignore[assignment]
    sys.stderr = _FilteredStream(sys.stderr, _LITELLM_SPAM)  # type: ignore[assignment]
