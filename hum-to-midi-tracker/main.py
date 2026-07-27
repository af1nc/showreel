"""Hum-to-MIDI: record a melody in your head before it dies.

Pipeline: audio → pitch track → note segmentation → grid quantise → MIDI file.

The production version of this idea uses a neural pitch model. The demo ships a
from-scratch autocorrelation tracker (a YIN-style difference function) so the whole
pipeline runs offline with numpy alone — the interesting part was never the model, it
is what you must do to raw pitch before it becomes *music*: segmenting a wobbling
contour into notes, and quantising human timing without flattening the phrasing.

Run:  python main.py --demo
"""

from __future__ import annotations

import argparse
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 22050
FRAME = 1024
HOP = 256
FMIN, FMAX = 80.0, 800.0  # singing range

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# ---------------------------------------------------------------------------
# 1. A synthetic "hum": a real melody sung imperfectly.
#    Detuned pitch, vibrato, sloppy timing, breath noise — like a person.
# ---------------------------------------------------------------------------

DEMO_MELODY = [  # (midi note, intended beats) — a simple hook in A minor
    (69, 1.0), (72, 0.5), (74, 0.5), (76, 1.0), (74, 0.5), (72, 0.5),
    (69, 1.0), (67, 0.5), (69, 1.5), (0, 0.5),
    (69, 0.5), (72, 0.5), (76, 1.0), (77, 0.5), (76, 0.5), (74, 1.0), (72, 2.0),
]
DEMO_TEMPO = 96.0


def synth_hum(seed: int = 7) -> np.ndarray:
    """Render the demo melody as a wobbly, human-ish hum."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / DEMO_TEMPO
    out = []
    for midi, beats in DEMO_MELODY:
        dur = beats * beat * rng.uniform(0.86, 1.1)  # sloppy timing
        n = int(dur * SR)
        t = np.arange(n) / SR
        if midi == 0:  # breath
            out.append(rng.normal(0, 0.004, n))
            continue
        f0 = 440.0 * 2 ** ((midi - 69) / 12)
        f0 *= 2 ** (rng.uniform(-25, 25) / 1200)  # detune ±25 cents
        vib = 1 + 0.006 * np.sin(2 * np.pi * 5.3 * t)  # vibrato
        phase = np.cumsum(2 * np.pi * f0 * vib / SR)
        tone = (
            0.6 * np.sin(phase)
            + 0.25 * np.sin(2 * phase)  # hum has a strong 2nd harmonic
            + 0.08 * np.sin(3 * phase)
        )
        env = np.minimum(1, np.minimum(t / 0.03, (dur - t) / 0.05).clip(0)) ** 0.7
        out.append(tone * env * 0.5 + rng.normal(0, 0.003, n))
    return np.concatenate(out).astype(np.float32)


# ---------------------------------------------------------------------------
# 2. Pitch tracking: YIN-style cumulative-mean difference, frame by frame.
# ---------------------------------------------------------------------------

def track_pitch(signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (times, f0) with f0=0 where the frame is unvoiced."""
    tau_min = int(SR / FMAX)
    tau_max = int(SR / FMIN)
    times, f0s = [], []

    for start in range(0, len(signal) - FRAME - tau_max, HOP):
        frame = signal[start : start + FRAME + tau_max]
        # Difference function d(tau), vectorised over lags.
        taus = np.arange(tau_min, tau_max)
        base = frame[:FRAME]
        d = np.array([np.sum((base - frame[tau : tau + FRAME]) ** 2) for tau in taus])
        # Cumulative-mean normalisation: turns absolute error into a unitless dip.
        cmnd = d * np.arange(1, len(d) + 1) / (np.cumsum(d) + 1e-12)
        # Take the FIRST dip under threshold, not the global minimum — the global
        # minimum loves subharmonics, and that is where octave errors come from.
        below = np.flatnonzero(cmnd < 0.15)
        best = int(below[0]) if len(below) else int(np.argmin(cmnd))
        # Walk to the local minimum of this dip, then refine sub-sample by parabola.
        while best + 1 < len(cmnd) and cmnd[best + 1] < cmnd[best]:
            best += 1
        tau = float(taus[best])
        if 0 < best < len(cmnd) - 1:
            a, b, c = cmnd[best - 1], cmnd[best], cmnd[best + 1]
            denom = a - 2 * b + c
            if abs(denom) > 1e-12:
                tau += 0.5 * (a - c) / denom
        voiced = cmnd[best] < 0.25 and np.std(base) > 0.01
        times.append(start / SR)
        f0s.append(SR / tau if voiced else 0.0)

    f0s = np.array(f0s)
    # A short median filter kills single-frame flaps without smearing note edges.
    if len(f0s) >= 5:
        padded = np.pad(f0s, 2, mode="edge")
        f0s = np.median(np.lib.stride_tricks.sliding_window_view(padded, 5), axis=1)
    return np.array(times), f0s


# ---------------------------------------------------------------------------
# 3. Segmentation: a wobbling contour becomes discrete notes.
# ---------------------------------------------------------------------------

@dataclass
class Note:
    midi: int
    start: float  # seconds
    dur: float


def segment(times: np.ndarray, f0s: np.ndarray) -> list[Note]:
    """Group voiced frames into notes; split when the median pitch jumps."""
    notes: list[Note] = []
    run: list[tuple[float, float]] = []

    def close(upto: float) -> None:
        if len(run) < 4:  # < ~50 ms of evidence is a glitch, not a note
            run.clear()
            return
        pitches = np.array([p for _, p in run])
        midi = int(np.round(69 + 12 * np.log2(np.median(pitches) / 440.0)))
        notes.append(Note(midi, run[0][0], upto - run[0][0]))
        run.clear()

    for t, f in zip(times, f0s):
        if f <= 0:
            close(t)
            continue
        if run:
            ref = np.median([p for _, p in run])
            if abs(12 * np.log2(f / ref)) > 0.6:  # >60 cents from the running note
                close(t)
        run.append((t, f))
    close(times[-1] if len(times) else 0.0)

    # Merge same-pitch neighbours split by a hiccup, then drop blips.
    merged: list[Note] = []
    for n in notes:
        if merged and merged[-1].midi == n.midi and n.start - (merged[-1].start + merged[-1].dur) < 0.07:
            merged[-1].dur = n.start + n.dur - merged[-1].start
        else:
            merged.append(n)
    return [n for n in merged if n.dur >= 0.09]


# ---------------------------------------------------------------------------
# 4. Quantise: snap to the grid without flattening the phrasing.
# ---------------------------------------------------------------------------

def quantise(notes: list[Note], tempo: float, grid: float = 0.25, strength: float = 0.85) -> list[Note]:
    """Snap starts/durations toward a beat grid. strength<1 keeps some humanity."""
    beat = 60.0 / tempo
    out = []
    for n in notes:
        b_start = n.start / beat
        b_dur = max(n.dur / beat, grid)
        snapped = round(b_start / grid) * grid
        start = b_start + (snapped - b_start) * strength
        dur = max(round(b_dur / grid) * grid, grid)
        out.append(Note(n.midi, start * beat, dur * beat))
    return out


# ---------------------------------------------------------------------------
# 5. A MIDI file, written from first principles. No library.
# ---------------------------------------------------------------------------

def write_midi(notes: list[Note], tempo: float, path: Path, ppq: int = 480) -> None:
    def vlq(n: int) -> bytes:  # variable-length quantity
        chunks = [n & 0x7F]
        while n > 0x7F:
            n >>= 7
            chunks.append((n & 0x7F) | 0x80)
        return bytes(reversed(chunks))

    events: list[tuple[int, bytes]] = []
    beat = 60.0 / tempo
    for n in notes:
        on = int(n.start / beat * ppq)
        off = int((n.start + n.dur) / beat * ppq)
        events.append((on, bytes([0x90, n.midi, 96])))
        events.append((off, bytes([0x80, n.midi, 0])))
    events.sort(key=lambda e: e[0])

    track = bytearray()
    track += vlq(0) + bytes([0xFF, 0x51, 0x03]) + int(60_000_000 / tempo).to_bytes(3, "big")
    clock = 0
    for tick, msg in events:
        track += vlq(tick - clock) + msg
        clock = tick
    track += vlq(0) + bytes([0xFF, 0x2F, 0x00])  # end of track

    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq))
        f.write(b"MTrk" + struct.pack(">I", len(track)) + bytes(track))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def piano_roll(notes: list[Note], tempo: float) -> str:
    if not notes:
        return "(no notes)"
    beat = 60.0 / tempo
    lo = min(n.midi for n in notes)
    hi = max(n.midi for n in notes)
    end = max(n.start + n.dur for n in notes)
    cols = int(end / beat * 4) + 1
    rows = []
    for midi in range(hi, lo - 1, -1):
        cells = [" "] * cols
        for n in notes:
            a = int(n.start / beat * 4)
            b = max(a + 1, int((n.start + n.dur) / beat * 4))
            for c in range(a, min(b, cols)):
                cells[c] = "█"
        name = f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"
        row_cells = [" "] * cols
        for n in notes:
            if n.midi != midi:
                continue
            a = int(n.start / beat * 4)
            b = max(a + 1, int((n.start + n.dur) / beat * 4))
            for c in range(a, min(b, cols)):
                row_cells[c] = "█"
        rows.append(f"{name:>4} │{''.join(row_cells)}")
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="synthesise a hum and transcribe it")
    ap.add_argument("--wav", type=Path, help="transcribe your own mono WAV instead")
    ap.add_argument("--tempo", type=float, default=DEMO_TEMPO)
    args = ap.parse_args()

    if args.wav:
        with wave.open(str(args.wav), "rb") as w:
            raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            signal = raw.astype(np.float32) / 32768.0
    else:
        print("synthesising a human-ish hum (detuned, vibrato, sloppy timing)…")
        signal = synth_hum()
        out_wav = Path("hum.wav")
        with wave.open(str(out_wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((signal * 32767).astype(np.int16).tobytes())
        print(f"  wrote {out_wav} ({len(signal)/SR:.1f}s)")

    times, f0s = track_pitch(signal)
    voiced = int(np.sum(f0s > 0))
    print(f"pitch track: {len(f0s)} frames, {voiced} voiced")

    raw_notes = segment(times, f0s)
    print(f"segmentation: {len(raw_notes)} notes before quantise")

    notes = quantise(raw_notes, args.tempo)
    midi_path = Path("melody.mid")
    write_midi(notes, args.tempo, midi_path)
    print(f"quantised to 1/16 grid at {args.tempo:.0f} BPM → {midi_path}\n")

    print(piano_roll(notes, args.tempo))
    print("\nnotes:", " ".join(f"{NOTE_NAMES[n.midi % 12]}{n.midi // 12 - 1}" for n in notes))


if __name__ == "__main__":
    main()
