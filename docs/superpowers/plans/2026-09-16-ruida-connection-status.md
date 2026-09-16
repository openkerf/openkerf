# Ruida connection and truthful status implementation plan

> Execution: subagent-driven-development for the isolated engine repair; root integrates OpenKerf. Review engine spec first, then correctness of the integrated change.

**Goal:** Repair UDP session ownership/recovery and show controller connectivity independently of job state, without redesigning the sidebar.

**Architecture:** Keep the pinned MeerK40t engine with a reviewable build-time patch until upstream accepts the fix. Only its session worker reads the transport; producers enqueue raw requests. Packet completion/failure is explicit so uploads do not guess from queue emptiness. OpenKerf consumes the connection separately from local job state.

**Tech stack:** Existing Python/pytest, stdlib threading/queue, Svelte/TypeScript/node:test, Docker.

## 1. Engine session (isolated worktree /tmp/meerk40t-ruida-fix)

- [x] Add real-session fake-transport tests in `test/test_ruida_session.py`: one I/O owner under reconnect, raw ENQ packaging, ordered/backpressured polling, ACK/reply timeout and recovery, shutdown/disconnect, failed UDP bind retry, acknowledged packet completion. No kernel/hardware/settings.
- [x] Run tests against existing code and record expected failures.
- [x] Repair `meerk40t/ruida/ruidasession.py`, `controller.py`, `udp_transport.py` as needed. Monitor never invokes transport-reading reconnect. Bound retries, preserve uncertainty after missing ACK (never silently resend an uncertain file block), clear flags on all outcomes, no arbitrary queue clearing.
- [x] Run session tests and existing Ruida tests. Review exact public completion API with integrator before finalizing.

## 2. OpenKerf integration and deployment

- [x] Add failing upload tests using the repaired session completion contract; delayed write/ACK and failed ACK must not yield upload success. Preserve legacy engine compatibility only if it remains honest; require the repaired API for guaranteed upload instead of silently falling back to queue polling.
- [x] Replace queue-clearing/queue-empty upload heuristics with explicit completion. Preserve monitor exclusion, upload mutual exclusion, no-start semantics and actionable failure messages.
- [x] Export engine diff to `deploy/patches/ruida-session.patch`; Docker fetches pinned source, checks/applies patch, installs it. Document equivalent local setup. Do not require an unpublished remote branch.

## 3. Independent UI connectivity

- [x] Add failing node tests: lost connection remains visible during busy/paused jobs; unknown never presents as confirmed connected; connected idle/busy/paused behavior is preserved.
- [x] Introduce a shared connection-state selector alongside existing job state. Apply on top/status/phone surfaces; connection problems retain warning/unknown appearance without changing job controls or stop availability. Remove eight-second UI masking.
- [x] Update catalogue sentences and relevant handbook pages; no layout redesign.

## 4. Verify and review

- [x] Run targeted and full API tests with isolated test fixtures; frontend node tests, svelte-check and static build.
- [x] Verify patch applies to pristine pinned engine and yields exactly the tested implementation. Run Docker smoke if daemon available, otherwise explicitly report limitation.
- [x] Independent spec/correctness review, address actionable issues, rerun affected checks.
- [x] Commit branches locally, leave production untouched, report hardware validation pending with idle/reconnect/upload-without-start checklist.

## Verification recorded 2026-09-16

- Engine: 31 tests passed, including real-Future cancellation, reconnect generation,
  reply matching, peer filtering and bind recovery; independent review cleared.
- Full API: 1622 passed, 17 skipped (optional dependencies); existing dependency,
  geometry and resource warnings remain. Real-session uploader integration passes.
- Frontend: 277 passed, 174 browser cases skipped because their dedicated servers
  were not running. Svelte check: zero errors, one existing unused CSS warning.
- Docker `openkerf:ruida-fix` built on arm64; all six smoke checks passed.
  SHA-256 comparison confirmed the five installed engine modules match the tested
  worktree exactly. Build checked patch application against pinned upstream source.
- Independent integration review caught and verified fixes for pause display and
  transfer continuation across reconnects.
- No controller, home network or production container was accessed. Actual Ubuntu,
  Cisco switch and controller firmware checks remain pending at home. Sidebar
  redesign (user's step 3) remains deferred.
