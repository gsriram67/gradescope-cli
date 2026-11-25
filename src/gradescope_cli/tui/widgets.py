"""Custom widgets for the gradescope-cli TUI."""

from __future__ import annotations

from typing import Any

from textual import events
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Tree

# Vim-style navigation, added to tables and trees.
VIM_NAV_BINDINGS: list[Binding] = [
    Binding("j", "cursor_down", "Down", show=False),
    Binding("k", "cursor_up", "Up", show=False),
]


class RowClickTable(DataTable[Any]):
    """A DataTable where a single click on a row selects it (RowSelected).

    Stock textual only emits RowSelected when clicking the already-highlighted
    row (or pressing enter); we want one click to open the row.
    """

    BINDINGS = [*DataTable.BINDINGS, *VIM_NAV_BINDINGS]

    async def _on_click(self, event: events.Click) -> None:
        meta = event.style.meta if event.style is not None else None
        if (
            meta is not None
            and "row" in meta
            and "column" in meta
            and self.cursor_type == "row"
            and isinstance(meta.get("row"), int)
            and meta["row"] >= 0  # -1 is the header row
        ):
            row_index = meta["row"]
            self.cursor_coordinate = Coordinate(row_index, meta["column"])
            row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
            self.post_message(DataTable.RowSelected(self, row_index, row_key))
            event.stop()
            return
        await super()._on_click(event)


class NavTree(Tree[Any]):
    """Tree with vim j/k cursor movement."""

    BINDINGS = [*Tree.BINDINGS, *VIM_NAV_BINDINGS]
