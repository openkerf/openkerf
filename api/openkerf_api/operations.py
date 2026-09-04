"""
The engine's layer list, in a file of its own.

The library got a path of its own this round (`openkerf -l`); the layer list did
not, and it has the same hole. `Elements` keeps it in
`Settings(self.kernel.name, "operations.cfg")` (`core/elements/elements.py:764`),
reads it at boot (`:773`) and writes it at shutdown (`:1526`) — and the directory
comes from the **kernel name**, so neither `-P/--profile` nor `ignore_settings`
reaches it. Every instance therefore shares one file with the app the user
actually works in. `api/tests/conftest.py` fences it off for the test suite by
patching `Settings`; a server in another process cannot be patched, so it needs a
path handed to it, which is what this does.

What it costs to leave it open is not hypothetical, and it is two things.

**The pictures stop being reproducible.** Measured while taking the handbook's
pre-flight shot: the fourth layer came out as "Engrave, 20 mm/s, 100%" where the
seeding asks for "Logo area, 300 mm/s, 30%", and the estimate under it read 2:22
instead of 1:19. That layer is not in the seeding at all — it comes from the
`[_default …]` sections of the developer's own `operations.cfg`, which
`init_default_operations_nodes` (`:1872`) loads as the set the engine files a new
shape under when its colour has no layer. So a screenshot script that seeds its
own state was still photographing somebody's settings.

**And it writes there.** Everything the script makes is in the list the engine
saves on the way out, so a run of the picture set leaves the handbook's layers in
the layer list of the app the user opens next.
"""

from pathlib import Path

from meerk40t.core.elements import elements as elements_module
from meerk40t.core.wordlist import Wordlist


def fence_operations(kernel, path):
    """Point the layer list at `path`, and forget the one the engine booted with.

    Four steps, and the last two are the half that is easy to miss:

    1. `op_data` is where the list is written at shutdown. Redirected, nothing this
       server does can reach the user's file. `Settings(None, <path>)` keeps the
       name as the whole path (`kernel/settings.py:30-35`), which is how an
       absolute one gets in.
    2. The wordlist lives in the same directory by construction
       (`elements.py:770` takes its directory from this file's), so it follows.
    3. The layers already in memory are the ones read out of the user's file at
       boot, before any of this could run. They are dropped and the fenced file is
       read instead — otherwise the fence stops the writing and not the reading,
       and the pictures stay unreproducible.
    4. `default_operations` is a *third* reader of the same file and the one that
       actually bit: it is what a new shape is filed under when its colour has no
       layer yet. Recomputed here, so it comes from the fenced file — and where
       that file has nothing to say, from the set the engine makes up itself
       (`elements.py:1895`), which is the same set on every machine.

    Returns the file it settled on, so the caller can say where it went.
    """
    file = Path(path).expanduser()
    file.parent.mkdir(parents=True, exist_ok=True)
    elements = kernel.elements
    elements.op_data = elements_module.Settings(None, str(file), create_backup=True)
    elements.mywordlist = Wordlist(kernel.version, str(file.parent))
    with elements.undofree():
        elements.clear_operations()
        elements.load_persistent_operations("previous")
    elements.init_default_operations_nodes()
    return file
