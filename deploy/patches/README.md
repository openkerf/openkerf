# Ruida session patch

`ruida-session.patch` applies to MeerK40t commit `5f68a45`. It contains the engine
repair and its fake-transport regression tests. It is applied by Docker during the
build, with no fallback to an unpatched engine. No upstream PR has been submitted.

For local development, from the OpenKerf repository root, create a separate engine
checkout (choose an unused destination):

```sh
git clone https://github.com/meerk40t/meerk40t.git /tmp/openkerf-engine
git -C /tmp/openkerf-engine checkout 5f68a45
git -C /tmp/openkerf-engine apply --check "$PWD/deploy/patches/ruida-session.patch"
git -C /tmp/openkerf-engine apply "$PWD/deploy/patches/ruida-session.patch"
python3 -m venv .venv
.venv/bin/pip install -e /tmp/openkerf-engine -e 'api[dev]'
.venv/bin/python -m pytest /tmp/openkerf-engine/test/test_ruida_session.py
```

One worker owns transport I/O. Explicit disconnect disables reconnection. Each write
returns a completion Future; UDP waits for ACK, USB for successful write, and memory
queries additionally require a matching reply. Uploads pin the session generation so
reconnect cannot silently resume half a file. A missing ACK is uncertain delivery:
the packet is not automatically replayed. UDP ACKs lack transaction IDs, so an
exceptionally late duplicate cannot be perfectly attributed.

Use a numeric controller IP: initial hostname resolution depends on the platform
resolver and can exceed the session's bounded shutdown wait.

Before replacing the patch with an upstream release, verify the completion API and
rerun the session/upload tests. At home, retain the previous image for rollback and
check idle polling, explicit disconnect/reconnect, cable interruption and recovery,
and a file upload **without starting the laser**. Compare logs/packet capture with
the visible connection status. Offline tests cannot validate controller firmware or
the Ubuntu/Cisco network path.
