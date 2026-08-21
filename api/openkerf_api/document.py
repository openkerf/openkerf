"""
Keeping track of whether the design has unsaved changes.

MeerK40t itself has no "changed since saving" flag, and without that flag you cannot see
whether you are throwing something away when opening a file. So we mark in one place: every
console command that does not demonstrably only read, plus every direct tree change.
"""

# Commands that do not change the design.
# `plan` builds a cut plan from the existing operations; it does not touch the element tree,
# so a time estimate does not make your design dirty.
READ_ONLY = {"version", "save", "flush", "channel", "help", "plan"}


class Document:
    def __init__(self):
        self.dirty = False

    def touch(self, command: str | None = None) -> None:
        if command is not None:
            first = command.strip().split(" ", 1)[0]
            if first in READ_ONLY:
                return
        self.dirty = True

    def clean(self) -> None:
        """After saving, opening or emptying, the file equals the design."""
        self.dirty = False
