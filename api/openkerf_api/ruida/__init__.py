"""
Our own line to a Ruida: UDP, framing and the session, without the engine's threads.

The engine still designs, plans and encodes (`build_job_bytes`, the `rdjob`
encoders, the swizzle table); what leaves this package is bytes on a socket. See
`plannen/2026-10-11-eigen-ruida-verbinding.md` in the working record.
"""

from .framing import Swizzler, frame, split
from .session import RuidaSession
from .transport import TransportError, TransportTimeout, UdpTransport

__all__ = [
    "RuidaSession",
    "Swizzler",
    "TransportError",
    "TransportTimeout",
    "UdpTransport",
    "frame",
    "split",
]
