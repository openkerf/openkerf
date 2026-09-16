"""Uploader against the actual engine session; no socket or kernel is created."""
import queue
import time
from types import SimpleNamespace

import pytest
from meerk40t.ruida.rdjob import ACK
from meerk40t.ruida.ruidasession import RuidaSession
from meerk40t.ruida.ruidatransport import TransportTimeout
from openkerf_api.edits import DesignError
from openkerf_api.ruida_upload import RuidaUpload


@pytest.mark.parametrize("missing_ack", [False, True])
def test_actual_session_confirms_final_upload_packet(monkeypatch, missing_ack):
    class Transport:
        connected = False
        def __init__(self):
            self.incoming = queue.Queue()
            self.writes = []
        def open(self):
            self.connected = True
        def close(self):
            self.connected = False
        def set_timeout(self, timeout):
            pass
        def write(self, data):
            self.writes.append(data)
            if not (missing_ack and data.endswith(b"last")):
                self.incoming.put(ACK)
        def read(self, size):
            try:
                return self.incoming.get(timeout=0.01)
            except queue.Empty:
                raise TransportTimeout()

    transport = Transport()
    monkeypatch.setattr("meerk40t.ruida.ruidasession.udp.UDPTransport", lambda service: transport)
    service = SimpleNamespace(interface="udp", safe_label="test",
        channel=lambda *a, **kw: lambda *a: None, signal=lambda *a: None)
    session = RuidaSession(service)
    session.set_swizzles(bytes, bytes)
    session._tries = 1
    session.open()
    try:
        deadline = time.monotonic() + 2
        while not session.connected:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        upload = RuidaUpload(SimpleNamespace())
        packets = [b"header", b"name", b"last"]
        if missing_ack:
            with pytest.raises(DesignError) as error:
                upload._send(session, packets, 1, "TEST", b"last")
            assert error.value.code == "upload.interrupted"
        else:
            assert upload._send(session, packets, 1, "TEST", b"last")["chunks"] == 1
        assert transport.writes.count(session._package(b"last")) == 1
    finally:
        session.shutdown()
