# Running this Mac installation

Start `Start OpenKerf.command` from the repository root, then open
http://127.0.0.1:8080. Keep its Terminal window open; stop with Ctrl+C.
If the server is already running, just open the URL instead of starting a second copy.

The launcher uses `.venv`, the local `meerk40t` checkout and `frontend/build`.
That checkout should be the engine at the revision `deploy/Dockerfile` pins
(`MEERK40T_REV`), **unpatched**; see the README's "Running it". A checkout that
still carries the old Ruida session patch is not what was tested; reinstall it
clean. Rebuild the frontend with `cd frontend && npm run build` after frontend
changes. The server listens only on localhost.

The existing KH-5030 profile and library in macOS Application Support are used.
A backup made before first launch is in `.venv/mac-profile-backup-20260916`.
Choose KH-5030 if another machine is selected. Connecting does not start a job.

## Validation and scope

The line to the KH-5030 is OpenKerf's own (UDP, ports 50200/40200, the numeric
address in the machine settings). It was validated on the machine on 11 October 2026,
with no other program connected to the controller: connecting and status, a file sent
without starting, moves, frame and home, three small burns, pause and resume, and stop
during a job. Not yet measured: a large raster file, focus, and a cable pulled
halfway through a job.

**Only one program at a time.** While this Mac is connected, the Docker installation
on the server must be stopped, and the other way round; LightBurn and MeerK40t the
same. Measured: with an OpenKerf container polling the same controller, only about
60 % of status reads were answered here, against 96 of 96 with it stopped.
