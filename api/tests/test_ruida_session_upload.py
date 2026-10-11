"""
The uploader against our own session, over a real UDP socket to the emulator peer.

This was the same question asked of the engine's `RuidaSession` (through the session
patch) when the upload still wrote on it: is the last packet confirmed, and is it
written exactly once when its ACK goes missing? The upload now writes on
`RuidaLink.send_file` and our `ruida/session.py`, so that is what is asked here.
"""

import time
from types import SimpleNamespace

import pytest

from openkerf_api.edits import DesignError
from openkerf_api.ruida.link import RuidaLink
from openkerf_api.ruida_upload import RuidaUpload
from ruida_peer import ruida_peer


@pytest.mark.parametrize("missing_ack", [False, True])
def test_our_session_confirms_the_final_upload_packet(missing_ack):
    packets = [b"\xe8\x02", b"\xe7\x01TEST\x00", b"\xd7"]
    with ruida_peer() as peer:
        link = RuidaLink(SimpleNamespace(address="127.0.0.1", magic=0x88),
                         send_port=peer.send_port, listen_port=0, reply_seconds=0.3,
                         poll_seconds=0.05)
        try:
            assert link.connect()["state"] == "connected"
            session = link.session
            if missing_ack:
                original = session.write

                def write(data, **kwargs):
                    if data == packets[-1]:
                        peer.drop_ack_next()
                    return original(data, **kwargs)

                session.write = write
            upload = RuidaUpload(SimpleNamespace())
            if missing_ack:
                with pytest.raises(DesignError) as error:
                    upload._send(link, packets, 1, "TEST", b"\xd7")
                assert error.value.code == "upload.interrupted"
                assert error.value.values == {"sent": 1, "chunks": 1, "announced": True}
                time.sleep(0.5)  # the session reconnects; the packet must not come again
            else:
                assert upload._send(link, packets, 1, "TEST", b"\xd7")["chunks"] == 1
            last = [entry for entry in peer.received if entry.payload == packets[-1]]
            assert len(last) == 1, [entry.action for entry in last]
            assert last[0].action == ("ack-dropped" if missing_ack else "ack")
        finally:
            link.close()
