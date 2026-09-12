"""Conversations over a protocol that cannot reply.

OSC — the control protocol most music and lighting hardware speaks — is fire-and-forget
UDP: you send a message at an address, and nothing about the protocol says an answer is
coming, or which question an answer belongs to if one arrives. This module builds a
request/response layer on top anyway:

  * a tiny OSC codec written from scratch (address + type tags + padded args)
  * a correlation table mapping reply addresses to pending futures, with timeouts
  * SO_REUSEPORT sharing, so multiple processes can listen on the same reply port

The demo starts a fake instrument (a UDP server that behaves like real hardware:
replies to queries, sometimes slowly, never for unknown addresses) and holds a
conversation with it — including the timeout path and two clients sharing one port.

Run:  python main.py --demo        (stdlib only)
"""

from __future__ import annotations


# The demos print box-drawing characters and arrows. A Windows console defaults
# to cp1252, which cannot encode them, so an unguarded print crashes the demo on
# a clean Windows machine. No-op on Linux and macOS.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import asyncio
import socket
import struct
import sys

HOST = "127.0.0.1"
SEND_PORT = 19100  # the "instrument" listens here
RECV_PORT = 19101  # replies come back here


# ---------------------------------------------------------------------------
# 1. OSC codec, from scratch. The format is simple and worth knowing:
#    padded address string, ","-prefixed type tags, then packed args.
# ---------------------------------------------------------------------------

def pad(b: bytes) -> bytes:
    """OSC pads strings/blobs to 4 bytes, always with at least one NUL for strings."""
    return b + b"\x00" * (4 - (len(b) % 4))


def encode(address: str, *args: float | int | str) -> bytes:
    tags = ","
    payload = b""
    for a in args:
        if isinstance(a, bool):  # bools ride as ints
            tags += "i"
            payload += struct.pack(">i", int(a))
        elif isinstance(a, int):
            tags += "i"
            payload += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"
            payload += struct.pack(">f", a)
        else:
            tags += "s"
            payload += pad(a.encode())
    return pad(address.encode()) + pad(tags.encode()) + payload


def decode(data: bytes) -> tuple[str, list]:
    def take_str(buf: bytes, at: int) -> tuple[str, int]:
        end = buf.index(b"\x00", at)
        return buf[at:end].decode(), (end + 4) & ~3

    address, i = take_str(data, 0)
    tags, i = take_str(data, i)
    args: list = []
    for t in tags[1:]:
        if t == "i":
            args.append(struct.unpack_from(">i", data, i)[0]); i += 4
        elif t == "f":
            args.append(round(struct.unpack_from(">f", data, i)[0], 6)); i += 4
        elif t == "s":
            s, i = take_str(data, i)
            args.append(s)
    return address, args


# ---------------------------------------------------------------------------
# 2. The client: request/response over fire-and-forget.
# ---------------------------------------------------------------------------

def shared_udp_socket(port: int) -> socket.socket:
    """A UDP socket several processes can bind at once (SO_REUSEPORT where available)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((HOST, port))
    sock.setblocking(False)
    return sock


#: One correlation table for the whole process, shared by every listener on the port.
#: This is the lesson SO_REUSEPORT teaches the hard way: the kernel delivers each
#: datagram to whichever bound socket it pleases, so replies must be resolved by
#: ADDRESS against shared state — never by which socket happened to receive them.
_PENDING: dict[str, asyncio.Future] = {}


class _ReplyProto(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr) -> None:
        address, args = decode(data)
        fut = _PENDING.pop(address, None)
        if fut and not fut.done():
            fut.set_result(args)
        # Replies nobody is waiting for are someone else's business — with a shared
        # port that is normal, not an error.


class Conversation:
    """Ask questions of hardware that only knows how to shout back."""

    def __init__(self, name: str, timeout: float = 0.5) -> None:
        self.name = name
        self.timeout = timeout
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            _ReplyProto, sock=shared_udp_socket(RECV_PORT)
        )

    async def ask(self, address: str, *args) -> list:
        """Send a query; await the reply that comes back on the same address."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _PENDING[address] = fut
        assert self._transport
        self._transport.sendto(encode(address, *args), (HOST, SEND_PORT))
        try:
            return await asyncio.wait_for(fut, self.timeout)
        except asyncio.TimeoutError:
            _PENDING.pop(address, None)
            raise TimeoutError(f"{address} — no reply within {self.timeout}s")

    def close(self) -> None:
        if self._transport:
            self._transport.close()


# ---------------------------------------------------------------------------
# 3. A fake instrument, faithful to how real hardware behaves.
# ---------------------------------------------------------------------------

async def fake_instrument() -> asyncio.DatagramTransport:
    state = {"tempo": 120.0, "tracks": 4, "playing": 0}

    class Proto(asyncio.DatagramProtocol):
        def connection_made(self, transport) -> None:
            self.transport = transport

        def datagram_received(self, data: bytes, addr) -> None:
            address, args = decode(data)
            if address == "/live/song/get/tempo":
                self.transport.sendto(encode(address, state["tempo"]), addr)
            elif address == "/live/song/set/tempo":
                state["tempo"] = float(args[0])
                self.transport.sendto(encode(address, state["tempo"]), addr)
            elif address == "/live/song/get/track_count":
                # Hardware is sometimes slow. The correlation layer must not care.
                async def slow():
                    await asyncio.sleep(0.2)
                    self.transport.sendto(encode(address, state["tracks"]), addr)
                asyncio.get_running_loop().create_task(slow())
            # Unknown addresses: silence. Exactly like the real thing.

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        Proto, local_addr=(HOST, SEND_PORT)
    )
    return transport


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

async def demo() -> None:
    instrument = await fake_instrument()
    print("fake instrument listening — replies to known queries, silence otherwise\n")

    a = Conversation("client-A")
    b = Conversation("client-B")
    await a.start()
    await b.start()  # second listener on the SAME reply port

    tempo = await a.ask("/live/song/get/tempo")
    print(f"A asks tempo          → {tempo[0]} BPM")

    new = await a.ask("/live/song/set/tempo", 96.0)
    print(f"A sets tempo to 96    → confirmed {new[0]} BPM")

    tracks = await b.ask("/live/song/get/track_count")
    print(f"B asks track count    → {tracks[0]} (reply took 200ms; future waited)")

    try:
        await a.ask("/live/song/get/does_not_exist")
    except TimeoutError as e:
        print(f"A asks the unknown    → {e}")

    both = await asyncio.gather(
        a.ask("/live/song/get/tempo"),
        b.ask("/live/song/get/track_count"),
    )
    print(f"A and B concurrently  → {both[0][0]} BPM, {both[1][0]} tracks")

    a.close(); b.close(); instrument.close()
    print("\nA one-way protocol, holding a conversation.")


if __name__ == "__main__":
    if "--demo" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    asyncio.run(demo())
