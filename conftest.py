"""Repository-root pytest bootstrap.

Makes the ``src`` layout importable without an editable install, so that
``python -m pytest`` works from a fresh checkout (and from the throw-away
copies created by ``tests/test_mutation.py``).
"""

from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parent / "src"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
