[← Showreel](..)

# 📻 UDP Request/Reply

![Formats & protocols](https://img.shields.io/badge/Formats_%26_protocols-f59e0b) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![stdlib only](https://img.shields.io/badge/stdlib-only-2ea44f) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

**Conversations over a protocol that cannot reply.** OSC, the control protocol that most
music and lighting hardware speaks, is fire-and-forget UDP. Nothing in it says an
answer is coming, or which question an answer belongs to. This builds a request/response
layer on top anyway, from scratch, stdlib only.

## Try it

```bash
python main.py --demo
```

The demo boots a fake instrument that behaves like real hardware, replies to known
queries, replies *slowly* to some, and answers unknown addresses with silence, then
holds a conversation with it: queries, confirmed writes, a clean timeout, and two
clients working concurrently through one shared reply port.

## The interesting part

- **The OSC codec is ~40 lines**, padded address, `,`-prefixed type tags, packed args.
  A wire format you can hold in your head is a wire format you can debug at 2 a.m.
- **Correlation is by address, against shared state.** `SO_REUSEPORT` lets several
  listeners bind one reply port, and the kernel then delivers each datagram to
  whichever socket it pleases. Resolve replies per-socket and your futures hang
  forever; resolve them by address against one shared table and every listener is
  interchangeable. The demo exercises exactly this.
- **Timeouts are part of the protocol you're inventing.** Hardware answers unknown
  addresses with silence, so the absence of a reply must be a first-class outcome,
  not an exception path that never fires.
