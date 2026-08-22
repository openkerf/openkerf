"""
Locking a shape: protected from moving, sizing and deleting.

Why this exists: the shapes you must not touch are the ones you touch by accident.
The alignment marks of a tile run, a sheet outline you drew round the material, a
jig you re-use every week — one drag box over the bed takes them with everything
else, and you only see it when the part comes out 3 mm off. LightBurn has a lock
for exactly this, and MeerK40t's own node model already carries it.

## What the engine gives us

`core/node/node.py:85` sets `self.lock = False` on every node, and lines 366-399
derive a whole family from it: `can_move()`, `can_scale()`, `can_rotate()`,
`can_skew()`, `can_modify()`, `can_alter()`, `can_update()`, `can_remove()`. The
engine's own console has `element lock` and `element unlock`
(`core/elements/branches.py:1338,1354`) which set nothing else.

So the flag is the engine's, and it is the same flag the wxPython interface uses:
lock a shape here, open the same design in MeerK40t, and it is locked there too.

## What a lock stops, and what it deliberately does not

It protects **geometry and existence**: moving, sizing, rotating, mirroring,
aligning, combining, offsetting, corners, simplifying, effects, editing nodes,
editing the text of a text shape, deleting, and cutting to the clipboard.

It does not protect **what the shape is for**: you can still put it in another
layer, give it a colour, a fill, or bridges, and you can still copy or duplicate
it. Those change what the laser does with the shape, not where the shape is — and
a locked alignment mark that cannot be given a layer would be a lock that stops
you working rather than one that stops an accident.

That line is a decision, not a technicality, so it is written on the page as well
(docs/canvas.md) and the refusal says which verb it refused.
"""

from .edits import DesignError


def is_locked(node) -> bool:
    """A node the user has locked. Missing attribute counts as unlocked."""
    return bool(getattr(node, "lock", False))


def locked_names(nodes) -> list[str]:
    """The ids of the locked nodes among these, in the order they were given."""
    return [node.id for node in nodes if is_locked(node)]


def refuse_locked(nodes, verb: str) -> None:
    """
    Stop an edit that would touch a locked shape.

    All or nothing on purpose: doing it to the four unlocked shapes of a selection
    of five and saying so afterwards leaves the user with a half-done alignment and
    no way back except undo. The refusal names the verb, because "3 shapes are
    locked" without it reads as though the whole app is stuck.
    """
    locked = [node for node in nodes if is_locked(node)]
    if not locked:
        return
    count = len(locked)
    raise DesignError(
        (
            f"{count} of the {len(nodes)} shapes you picked are locked, so nothing was "
            f"{verb}. Unlock them first — the lock is there to stop exactly this."
            if count != len(nodes)
            else (
                f"This shape is locked, so it was not {verb}. Unlock it first."
                if count == 1
                else f"All {count} shapes are locked, so nothing was {verb}. "
                "Unlock them first."
            )
        ),
        code="edit.locked",
        values={"locked": count, "picked": len(nodes), "verb": verb},
    )
