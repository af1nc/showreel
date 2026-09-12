[← Showreel](..)

# 🎤 Hum-to-MIDI Tracker

![Formats & protocols](https://img.shields.io/badge/Formats_%26_protocols-f59e0b) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

**The melody in your head dies before you can write it down.** This turns a hummed
voice memo into real MIDI notes: audio → pitch track → note segmentation → grid
quantise → a `.mid` file any DAW can open.

## Try it

```bash
pip install -r requirements.txt
python main.py --demo
```

The demo synthesises a deliberately human hum (detuned ±25 cents, vibrato, sloppy
timing, breath gaps) then transcribes it back and prints the piano roll. You can feed
it your own recording with `python main.py --wav yourfile.wav`.

## The interesting part

The model was never the hard bit. What stands between raw pitch and *music* is
judgment:

- **Octave errors are a selection bug, not a model bug.** A YIN-style tracker that
  takes the global minimum of the difference function loves subharmonics. Taking the
  *first* dip under threshold, then refining sub-sample with a parabola, is the
  difference between a melody and octave soup.
- **Segmentation is where notes are born.** A wobbling contour becomes discrete notes
  by splitting on >60-cent jumps from the running median, merging same-pitch
  neighbours split by hiccups, and refusing to believe anything under 90 ms.
- **Quantise with a strength dial, not a snap.** 85% of the way to the 1/16 grid keeps
  the phrasing human; 100% flattens it into a ringtone.
- **The MIDI file is written from first principles**, variable-length quantities,
  tempo meta event, note on/off deltas. No MIDI library.

Everything runs offline. The only dependency is numpy.
