from __future__ import annotations

import sys
from pathlib import Path

# Make `mvp/src` importable for plain `pytest` runs from repo root.
MVP_SRC = Path(__file__).resolve().parents[1] / "src"
if str(MVP_SRC) not in sys.path:
    sys.path.insert(0, str(MVP_SRC))

