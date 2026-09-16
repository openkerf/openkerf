# Running this Mac installation

Start `Start OpenKerf.command` from the repository root, then open
http://127.0.0.1:8080. Keep its Terminal window open; stop with Ctrl+C.
If the server is already running, just open the URL instead of starting a second copy.

The launcher uses `.venv`, the local patched `meerk40t` checkout and
`frontend/build`. Rebuild the frontend with `cd frontend && npm run build`
after frontend changes. The server listens only on localhost.

The existing KH-5030 profile and library in macOS Application Support are used.
A backup made before first launch is in `.venv/mac-profile-backup-20260916`.
Choose KH-5030 if another machine is selected. Connecting does not start a job.

## Validation and scope

The structural session repair and Job panel cleanup are on `codex/mac-runtime`
(app commit 4ec9d12, engine commit 0f7d9f9). The experimental acknowledged-read
retry remains in the separate diagnostic worktree and is not enabled here.
The user stopped the Debian network investigation and chose native Mac operation.
Docker on the original server remains stopped.

The earlier Mac status-only probe completed 866 reads without retries or failures.
Full application startup and real-device idle connectivity were checked locally:
60 consecutive one-second API samples remained connected, with 621 sends/ACKs,
no NAKs or dropped packets. Frontend build and 65 targeted regression tests passed.
Physical link interruption/recovery and file upload without starting the laser
still require validation. No laser job was started during setup.
