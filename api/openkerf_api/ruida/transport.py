"""
The UDP socket to one Ruida, and nothing above it.

A Ruida listens on 50200 and answers on 40200 (`ruida/udp_transport.py:18-19`);
we send from the socket we listen on, as the engine does. Both ports are
arguments only so a test can use ephemeral ones on 127.0.0.1.

**A numeric address, refused otherwise.** The engine resolves a host name with
`gethostbyname` on every open (`udp_transport.py:37` with the former session patch), on
the worker that also owns shutdown, and the patch's README warns that the
platform resolver can take longer than the bounded shutdown wait. A laser on a
workshop network has a fixed IP anyway, so we take the IPv4 literal and never
ask a resolver: a name is a `ValueError` when the transport is made, which is
when the user can still fix it.

Only datagrams from that address *and* the controller's send port are taken;
anything else is counted in `dropped` and skipped, so a second laser or a stray
broadcast cannot pass for an ACK.
"""

import ipaddress
import socket
import time

SEND_PORT = 50200
LISTEN_PORT = 40200

#: The engine's receive slice (`udp_transport.py:26`, `_s_to = 0.25`): how long
#: one `receive` waits before it gives the caller its turn back.
RECEIVE_SECONDS = 0.25

#: Ample for anything the controller sends us: the replies we wait for are one
#: or nine bytes.
RECEIVE_BYTES = 2048


class TransportError(ConnectionError):
    """The socket could not be opened, or a send failed."""


class TransportTimeout(TimeoutError):
    """Nothing arrived from the peer within the wait."""


class UdpTransport:
    """One socket, opened, used and closed by one thread: the session's worker."""

    def __init__(self, host: str, *, send_port: int = SEND_PORT,
                 listen_port: int = LISTEN_PORT, bind_host: str = "",
                 receive_seconds: float = RECEIVE_SECONDS):
        try:
            self.host = str(ipaddress.IPv4Address(host))
        except ValueError as error:
            raise ValueError(
                f"The Ruida's address must be a numeric IPv4 address, not {host!r}."
            ) from error
        self.send_port = send_port
        self.listen_port = listen_port
        self.bind_host = bind_host
        self.receive_seconds = receive_seconds
        self.socket: socket.socket | None = None
        self.dropped = 0

    @property
    def peer(self) -> tuple[str, int]:
        return (self.host, self.send_port)

    @property
    def is_open(self) -> bool:
        return self.socket is not None

    @property
    def local_address(self) -> tuple[str, int] | None:
        return self.socket.getsockname() if self.socket is not None else None

    def open(self) -> None:
        if self.socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.receive_seconds)
            sock.bind((self.bind_host, self.listen_port))
        except OSError as error:
            sock.close()
            raise TransportError(str(error)) from error
        self.socket = sock

    def close(self) -> None:
        sock, self.socket = self.socket, None
        if sock is not None:
            sock.close()

    def send(self, packet: bytes) -> None:
        if self.socket is None:
            raise TransportError("The UDP socket is closed.")
        try:
            self.socket.sendto(packet, self.peer)
        except OSError as error:
            raise TransportError(str(error)) from error

    def receive(self, seconds: float | None = None) -> bytes:
        """The next datagram from the peer, waiting at most `seconds`."""
        if self.socket is None:
            raise TransportError("The UDP socket is closed.")
        wait = self.receive_seconds if seconds is None else seconds
        deadline = time.monotonic() + wait
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TransportTimeout()
            self.socket.settimeout(left)
            try:
                data, sender = self.socket.recvfrom(RECEIVE_BYTES)
            except TimeoutError:
                raise TransportTimeout() from None
            except OSError as error:
                raise TransportError(str(error)) from error
            if sender[:2] == self.peer:
                return data
            self.dropped += 1

    def drain(self) -> int:
        """Throw away whatever is already waiting; the number thrown away.

        Called before a new packet goes out, so an answer that came in after its
        own transaction gave up cannot be taken for the answer to the next one.
        It cannot help with one that is still on its way.
        """
        if self.socket is None:
            return 0
        count = 0
        self.socket.setblocking(False)
        try:
            while True:
                try:
                    self.socket.recvfrom(RECEIVE_BYTES)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError as error:
                    raise TransportError(str(error)) from error
                count += 1
        finally:
            self.socket.settimeout(self.receive_seconds)
        return count
