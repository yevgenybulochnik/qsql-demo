"""Effect-only sink: the cell runs for its side effects and lands nothing.

Selected with ``-- @output: { type: none }``. Such a cell cannot be ``ref()``'d —
there is no landed relation to read back (the compiler rejects any ref to it).
"""

from __future__ import annotations

from typing import Any

from ..errors import ConfigError
from ..models import RenderedCell
from ..registry import sink
from .base import Sink


@sink("none")
class NoneSink(Sink):
    lands_output = False

    def write(self, cell: RenderedCell, view: str, conn: Any) -> tuple[int, str]:
        return 0, "none"  # the executor ran the statements for effect; nothing to land

    def ref_expr(self, cell_name: str) -> str:
        raise ConfigError(
            f"cell {cell_name!r} uses sink 'none' and lands nothing; it cannot be ref()'d"
        )
