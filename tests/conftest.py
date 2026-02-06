from __future__ import annotations

import sys
from pathlib import Path


# Ensure tests run against the workspace source tree even if a wheel is installed.
SRC = (Path(__file__).resolve().parents[1] / "src").as_posix()
if SRC not in sys.path:
    sys.path.insert(0, SRC)
