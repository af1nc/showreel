# correction-taught-classifier

**A classifier that learns from being told off — without retraining.** When a human
corrects a label, most systems log it and keep making the same mistake until the next
fine-tune. Here every correction becomes teaching, immediately: it is embedded, stored,
and retrieved as a few-shot example whenever a similar document appears.

## Try it

```bash
python main.py --demo
```

Stdlib only. Day 1: a school fee reminder reads like a newsletter and is misfiled. One
human correction. Day 30: the next term's reminder — different words, same shape — is
filed correctly, with the retrieved teaching visible in the prompt log. An unrelated
travel document is *not* dragged toward the correction.

## The interesting part

- **A similarity floor (0.70), because noise teaches nothing.** Retrieval without a
  floor turns one correction into a magnet that bends everything near it.
- **Prompt assembly order is a caching decision.** Few-shot examples are injected
  *after* the stable system prefix, so an LLM's prompt cache keeps hitting on
  everything that never changes and pays only for what does.
- **Near-exact matches (>0.85) boost confidence.** If the household already taught
  this precise pattern, the system should stop second-guessing it — that is how
  repeated patterns graduate to auto-accept.
- **The embedding is swappable.** The demo uses deterministic char-trigram hashing so
  it runs offline; the floor/boost/injection mechanism is identical with a real
  embedding model and a real LLM behind it.
