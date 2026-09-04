"""
What the machine's one connection is carrying, asked in one place by everybody.

A Ruida has **one** connection, and everything we send goes down the same
`send_q` on `active_session` — the blocks of a file upload
(`ruida_upload.py`), a jog through `RuidaDriver.move_abs` (`ruida/driver.py:305`,
`output=self.controller.write`), the cutcode of a burning job, and the realtime
pause and resume (`ruida/controller.py:416-422`,
`job.pause_process(output=self.write)`). The receiving side hangs whatever
arrives on the same `RDJob` and does not separate the streams: measured against
the engine's own emulator, a burn of 5463 bytes with an upload dropped in halfway
comes out as one job of 5882 bytes, the burn's own bytes no longer contiguous,
and **0** parse failures to warn anybody.

So the check has to be here rather than on the screen. That argument is not ours;
it is written in `MachineControl._idle()` and it is the reason this layer exists:
the interface is advice, and a second tab, a phone or a curl command goes
straight through it.

**Two questions, not one with a flag.** They look alike and they contradict each
other on exactly one thing, the queue. "Is the head moving?" wants the queue
*out* — the movers go through the spooler themselves, so counting it would make
them refuse each other. "Is the line in use?" wants it *in* — a queued job is one
the spooler is about to pick up and write down the line. A flag would put that
choice at the call site, which is where it gets copied wrongly the moment a
fourth reader appears, and the name would be lying for one of its two values.

Measured, on the dummy device, one `motion.jog(1, 0)`: the spooler holds one job
with status `Waiting` and `is_running()` `False`, unchanged a second later. So
both halves of that are real — a mover counting the queue refuses every jog after
the first, and an upload not counting it starts on top of a job about to run.

**A code, not a sentence.** `the_line_is_in_use` answers `'burning'`, `'queued'`,
`'uploading'` or `None` — the same shape as `jobPhase` in `api.ts` and
`offerState` in `library.svelte.ts`. Callers read it and decide for themselves
which answers concern them, which is the whole point: the movers act on
`'uploading'` and ignore `'queued'`, the upload does the opposite.

**The refusal, though, is one sentence and not six.** The plan was for each
caller to word its own, and the catalogue will not have it: `i18n.test.ts`
compares every `DesignError` code in this package against `en.ts` word for word,
so a code has exactly one English sentence. Six wordings would mean six codes and
six catalogue entries in every language for one situation — a file is going down
the line, wait. Measured by running it: the first version of this failed with
`api.upload.whileBurning ... API: ... en : ...`, and it also caught an f-string
that had reached the catalogue as a literal `{}`. So `refuse_while_a_file_is_being_sent`
says it once, and which button was pressed is already in front of the user.

**Why this module and not `machine.py`.** That was the proposal, on the grounds
that `ruida_upload` already imports from there. It cannot be: `commands.py` is a
reader too — the guard on `start_job` belongs in the runner, where the tile burn
(`tilerun.py:734`) and the series burn (`series.py:2278`) go through the same
line as the route — and `machine.py` imports `CommandRunner`. Measured, with the
import written that way round: `ImportError: cannot import name 'CommandRunner'
from partially initialized module 'openkerf_api.commands'`. So the questions live
one layer below both, in a module that imports nothing of ours.
"""

import threading
import weakref
from contextlib import contextmanager

#: One claim per kernel, and no attribute on the engine's own objects. Weak, so a
#: kernel that goes away takes its claim with it — tests build a great many.
_CLAIMS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_GUARD = threading.Lock()


def _claim_for(kernel) -> threading.Lock:
    with _GUARD:
        claim = _CLAIMS.get(kernel)
        if claim is None:
            claim = threading.Lock()
            _CLAIMS[kernel] = claim
        return claim


def _spooler(kernel):
    return getattr(getattr(kernel, "device", None), "spooler", None)


def a_job_is_running(kernel) -> bool:
    """Whether this machine is executing something right now.

    For the readers that ask about the head: `MachineControl._idle()`. A
    *running* job and not the queue, for the reason measured above — the movers
    go through the spooler themselves and would otherwise block each other.

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


def the_line_is_in_use(kernel) -> str | None:
    """What is on the connection: `'burning'`, `'queued'`, `'uploading'`, `None`.

    A code and not a refusal, so each caller says it in its own words — a jog, a
    burn and an upload are three different things to be told you cannot do.

    `'queued'` is the state `is_running()` cannot see: `LaserJob.__init__` sets
    `_stopped = True` and only `execute()` clears it (`core/laserjob.py:34,89`),
    so a job that has been spooled and not yet picked up reports `False`. The
    screen has always known this — `jobPhase` calls it `'queued'` and `jobBusy`
    counts it as busy (`frontend/src/lib/api.ts:422-437`) — which left the API
    check weaker than the interface it is supposed to be the real version of.

    The order is the order of certainty, not of severity: something actually
    running is a more definite answer than something merely queued. A caller that
    cares about only one of the three tests for that one; nothing here decides
    for it.
    """
    if a_job_is_running(kernel):
        return "burning"
    spooler = _spooler(kernel)
    if spooler is not None:
        try:
            if list(spooler.queue):
                return "queued"
        except Exception:  # pragma: no cover - the spooler must not break us
            pass
    if a_file_is_being_sent(kernel):
        return "uploading"
    return None


def a_file_is_being_sent(kernel) -> bool:
    """Whether an upload is holding this machine's line right now."""
    claim = _claim_for(kernel)
    if claim.acquire(blocking=False):
        claim.release()
        return False
    return True


def refuse_while_a_file_is_being_sent(kernel) -> None:
    """The one refusal for everything that would write while a file is going out.

    One sentence and one code, for the reason in the module docstring: the
    catalogue holds one English sentence per code and `i18n.test.ts` checks it.
    The remedy is the same wherever you meet this — wait until the file is there
    — and which button you pressed the user already knows.

    `DesignError` is fetched here rather than at the top of the module, the same
    way `commands.py` does it: `edits` imports `commands`, so a module-level
    import would close a ring the moment `commands` reads this module. Nothing
    else in here imports anything of ours, which is what lets every layer above
    ask these questions.
    """
    from .edits import DesignError

    if the_line_is_in_use(kernel) == "uploading":
        raise DesignError(
            "A file is being sent to the machine. Wait until it is there and then "
            "try again: anything sent now lands in the middle of that file, and "
            "the machine gives no sign of it.",
            code="machine.sendingAFile",
        )


@contextmanager
def sending_a_file(kernel):
    """Hold the line for the length of one upload, and say so to everybody.

    A context manager rather than an object passed around the routes: the flag
    has to be visible to `_idle()` and to `start_job`, which have no reason to
    know a `RuidaUpload` exists.

    It raises nothing and refuses nothing — `claimed` comes back `False` when
    somebody already has the line, and `upload()` writes that refusal itself,
    with its own code. Never blocking: a caller that waited would hold a
    threadpool thread through somebody else's whole build and send, and then put
    a second file on the panel that nobody asked for twice, which is what a
    double-click is.

    One mechanism and not two. The proposal was to keep `RuidaUpload._sending`
    beside this, but "an upload is running" is one fact, and two places holding
    it is two places to disagree — which is the shape of the bug this whole round
    is about: a lock only its owner could read.
    """
    claim = _claim_for(kernel)
    claimed = claim.acquire(blocking=False)
    try:
        yield claimed
    finally:
        if claimed:
            claim.release()
