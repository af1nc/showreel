[← Showreel](..)

# 🗣️ Chat Export Voice

![Formats & protocols](https://img.shields.io/badge/Formats_%26_protocols-f59e0b) ![Node.js](https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

**Your chat exports know how you write.** Years of talking to AI assistants leaves an
unusual corpus behind: thousands of messages written by *you*, asking, arguing,
thinking out loud, interleaved with machine replies nobody needs. This extracts the
human side and distils a small profile of how a person actually writes.

## Try it

```bash
node main.mjs --demo
```

Zero dependencies. The demo parses three synthetic exports in the three real dialects:
a ChatGPT export (a graph of mapping nodes), a Claude export (`chat_messages` with two
different content shapes), and a generic `messages[]` array. It keeps only the human's
messages, collapses duplicates across exports, and prints the voice profile: message
length, question vs imperative ratio, favourite words, longest thought.

## The interesting part

- **Every vendor invented a different container for the same conversation.** One is a
  graph, one is a list with two content encodings, one is the shape everyone assumes.
  The parsers funnel all of them into `string[]` and let plain text be the fallback.
- **The machine's replies are never loaded.** Not filtered out later, never kept.
  What survives is a corpus in one voice, ready to seed a persona, a style guide, or
  an honest look in the mirror.
- **Dedupe across exports, not within one.** People re-ask the same question in three
  apps; normalised-whitespace, case-folded comparison collapses them to one thought.

## package.json

```json
{ "scripts": { "demo": "node main.mjs --demo" } }
```
