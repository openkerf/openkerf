"""
What the machine is busy with, asked in one place by everybody who could interfere.

A Ruida has **one** connection, and everything we send goes down the same
`send_q` on `active_session` — the blocks of a file upload
(`ruida_upload.py`), a jog through `RuidaDriver.move_abs` (`ruida/driver.py:305`,
`output=self.controller.write`), the cutcode of a burning job, and the realtime
pause and resume (`ruida/controller.py:416-422`, `job.pause_process(output=self.write)`).
The receiving side hangs whatever arrives on the same `RDJob` and does not
separate the streams: measured against the engine's own emulator, a burn of 5463
bytes with an upload dropped in halfway comes out as one job of 5882 bytes, the
burn's own bytes no longer contiguous, and **0** parse failures to warn anybody.

So two things must never be happening at once, and the check has to be here
rather than on the screen. That argument is not ours; it is written in
`MachineControl._idle()` and it is the reason this whole layer exists: the
interface is advice, and a second tab, a phone or a curl command goes straight
through it.

**Two questions and not one, deliberately.** They look like the same question
with a flag, and the reviewer asked whether one function with a parameter would
do. It would not, and a measurement says why. `a_job_is_running` must not count
what is merely queued, because the movers ask it about *their own* kind of work:
measured on the dummy device, one `motion.jog(1, 0)` leaves a job in the spooler
with status `Waiting` and `is_running()` `False`, and it was still sitting there a
second later — so a mover that counted the queue would refuse every jog after the
first. `the_spooler_has_work` must count exactly that, because a `Waiting` job is
one the spooler is about to pick up and write down the line we are using.

Opposite needs, so opposite answers, each with its own name and its own reason.
A boolean argument would have put that reasoning at the call sites instead of
here, which is the thing this module exists to prevent.
"""

import threading
import weakref

#: One claim per kernel, and no attribute on the engine's own objects. Weak, so a
#: kernel that goes away takes its lock with it — tests build a great many.
_CLAIMS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_GUARD = threading.Lock()


def _claim_for(kernel) -> threading.Lock:
    with _GUARD:
        claim = _CLAIMS.get(kernel)
        if claim is None:
            claim = threading.Lock()
            _CLAIMS[kernel] = claim
        return claim


def a_job_is_running(kernel) -> bool:
    """Whether this machine is executing something right now.

    Asked by `MachineControl._idle()` before the head moves. A *running* job and
    not the queue: the movers go through the spooler themselves, and on the
    measurement above they would otherwise block each other for as long as the
    move before them lasts — on the dummy device, for ever.

    A spooler that cannot answer counts as not running: a broken read is not
    evidence of a burn, and the refusals built on this are not what keeps a laser
    from firing; they keep two things off one connection.
    """
    spooler = _spooler(kernel)
    if spooler is None:
        return False
    try:
        return any(job.is_running() for job in list(spooler.queue))
    except Exception:  # pragma: no cover - the spooler must not break us
        return False


def the_spooler_has_work(kernel) -> bool:
    """Whether anything is queued *or* running — the question an upload asks.

    `is_running()` alone is not enough here, and the gap is measured:
    `LaserJob.__init__` sets `_stopped = True` and only `execute()` clears it
    (`core/laserjob.py:34,89`), so a job that has been spooled and not yet picked
    up reports `False`. Measured on the dummy device, one jog later: one job,
    status `Waiting`, `is_running()` `False`, unchanged a second on.

    The screen has known this all along — `jobPhase` calls that state `'queued'`
    and `jobBusy` counts it as busy (`frontend/src/lib/api.ts:422-437`) — which
    made the API check weaker than the interface it is supposed to be the real
    version of.
    """
    spooler = _spooler(kernel)
    if spooler is None:
        return False
    try:
        return bool(list(spooler.queue))
    except Exception:  # pragma: no cover - the spooler must not break us
        return False


def _spooler(kernel):
    return getattr(getattr(kernel, "device", None), "spooler", None)


def a_file_is_being_sent(kernel) -> bool:
    """Whether an upload is holding this machine's line right now."""
    claim = _claim_for(kernel)
    if claim.acquire(blocking=False):
        claim.release()
        return False
    return True


def claim_the_line(kernel) -> bool:
    """Take the line for a file, or say no because somebody already has it.

    Never blocks. A caller that waited would hold a threadpool thread through
    somebody else's whole build and send, and then put a second file on the panel
    that nobody asked for twice — which is what a double-click is.
    """
    return _claim_for(kernel).acquire(blocking=False)


def release_the_line(kernel) -> None:
    claim = _claim_for(kernel)
    if claim.locked():
        claim.release()


def refuse_while_a_file_is_being_sent(kernel) -> None:
    """The one refusal for everything that would write while a file is going out.

    One sentence and one code for all of them, because the situation and the
    remedy are the same wherever you meet it: the line is carrying a file, wait
    until it has. What differs is only which button you pressed, and that is
    already in front of the user.

    `DesignError` is fetched here rather than at the top of the module, the same
    way `commands.py` does it: `edits` imports `commands`, so a module-level
    import would close a ring the moment `commands` reads this module. Nothing
    else in here imports anything of ours, which is what lets every layer above
    ask these questions.
    """
    from .edits import DesignError

    if a_file_is_being_sent(kernel):
        raise DesignError(
            "A file is being sent to the machine. Wait until it is there, and "
            "then do this: anything sent now goes into the middle of that file, "
            "and the machine gives no sign of it.",
            code="machine.sendingAFile",
        )
