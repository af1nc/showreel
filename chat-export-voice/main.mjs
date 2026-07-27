// Your chat exports know how you write.
//
// Years of talking to AI assistants leaves behind an unusual corpus: thousands of
// messages written by YOU — asking, arguing, thinking out loud — interleaved with
// machine replies nobody needs. This extracts the human side: parse the export
// formats the major assistants produce, keep only the person's own messages, and
// distil a small profile of how they actually write.
//
// Supported shapes: ChatGPT export (mapping graph), Claude export (chat_messages),
// a generic messages[] array, and plain text as a fallback.
//
// Run:  node main.mjs --demo        (zero dependencies)

// ---------------------------------------------------------------------------
// 1. Parsers — one per export dialect, all funnelling into string[].
// ---------------------------------------------------------------------------

export function extractUserMessages(raw) {
  const text = raw.trim();
  if (!text) return [];
  if (text.startsWith("[") || text.startsWith("{")) {
    try {
      const msgs = parseJsonExport(JSON.parse(text));
      if (msgs.length) return dedupe(msgs);
    } catch {
      /* not JSON — fall through to plain text */
    }
  }
  return dedupe(
    text
      .split(/\n{2,}/)
      .map((s) => s.trim())
      .filter((s) => s.length > 20),
  );
}

function parseJsonExport(data) {
  const out = [];
  const convos = Array.isArray(data) ? data : (data.conversations ?? [data]);
  for (const c of convos) {
    // ChatGPT: a graph — mapping{ id -> { message: { author:{role}, content:{parts} } } }
    if (c?.mapping && typeof c.mapping === "object") {
      for (const node of Object.values(c.mapping)) {
        const m = node?.message;
        if (m?.author?.role === "user") {
          const t = (m.content?.parts ?? [])
            .filter((p) => typeof p === "string")
            .join(" ")
            .trim();
          if (t) out.push(t);
        }
      }
    }
    // Claude: chat_messages[ { sender:'human', text | content:[{text}] } ]
    if (Array.isArray(c?.chat_messages)) {
      for (const m of c.chat_messages) {
        if (m?.sender === "human") {
          const t = (m.text ?? (m.content ?? []).map((x) => x?.text ?? "").join(" ")).trim();
          if (t) out.push(t);
        }
      }
    }
    // Generic: messages[ { role:'user', content } ]
    if (Array.isArray(c?.messages)) {
      for (const m of c.messages) {
        if (m?.role === "user" && typeof m.content === "string" && m.content.trim()) {
          out.push(m.content.trim());
        }
      }
    }
  }
  return out;
}

function dedupe(msgs) {
  const seen = new Set();
  return msgs.filter((m) => {
    const key = m.toLowerCase().replace(/\s+/g, " ");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ---------------------------------------------------------------------------
// 2. The voice profile — small, honest statistics about how a person writes.
// ---------------------------------------------------------------------------

const STOPWORDS = new Set(
  "the a an and or but if then of to in on for with is are was were be been i you it this that my me we our can could would should have has do does not no yes so at as by from".split(" "),
);

export function voiceProfile(messages) {
  const words = messages.flatMap((m) => m.toLowerCase().match(/[a-z']{2,}/g) ?? []);
  const freq = new Map();
  for (const w of words) {
    if (!STOPWORDS.has(w)) freq.set(w, (freq.get(w) ?? 0) + 1);
  }
  const favourites = [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);

  const questions = messages.filter((m) => m.includes("?")).length;
  const imperatives = messages.filter((m) =>
    /^(make|build|write|show|give|fix|add|remove|create|explain)\b/i.test(m),
  ).length;
  const avgWords = words.length / Math.max(messages.length, 1);

  return {
    messages: messages.length,
    avgWords: Math.round(avgWords * 10) / 10,
    questionShare: Math.round((questions / Math.max(messages.length, 1)) * 100),
    imperativeShare: Math.round((imperatives / Math.max(messages.length, 1)) * 100),
    favourites: favourites.map(([w, n]) => `${w}×${n}`),
    sample: messages.toSorted((a, b) => b.length - a.length)[0] ?? "",
  };
}

// ---------------------------------------------------------------------------
// Demo: three synthetic exports, one person, one voice.
// ---------------------------------------------------------------------------

const CHATGPT_EXPORT = JSON.stringify([
  {
    mapping: {
      a: { message: { author: { role: "user" }, content: { parts: ["Make the landing page darker. The starfield needs to feel infinite, not decorative."] } } },
      b: { message: { author: { role: "assistant" }, content: { parts: ["Sure! Here is a darker palette…"] } } },
      c: { message: { author: { role: "user" }, content: { parts: ["Why does every dashboard look the same? Show me one that respects the data."] } } },
    },
  },
]);

const CLAUDE_EXPORT = JSON.stringify({
  conversations: [
    {
      chat_messages: [
        { sender: "human", text: "Build the prototype properly or not at all — no mock data pretending to be real." },
        { sender: "assistant", text: "Understood. I'll wire the real source…" },
        { sender: "human", content: [{ text: "Can we make the transition feel like falling through the interface?" }] },
      ],
    },
  ],
});

const GENERIC_EXPORT = JSON.stringify({
  messages: [
    { role: "user", content: "Make the landing page darker. The starfield needs to feel infinite, not decorative." },
    { role: "assistant", content: "Noted." },
    { role: "user", content: "Fix the spacing before anyone else sees it. Details are the product." },
  ],
});

function demo() {
  const sources = [
    ["chatgpt-export.json", CHATGPT_EXPORT],
    ["claude-export.json", CLAUDE_EXPORT],
    ["generic-export.json", GENERIC_EXPORT],
  ];

  let all = [];
  for (const [name, raw] of sources) {
    const msgs = extractUserMessages(raw);
    console.log(`${name.padEnd(22)} → ${msgs.length} human messages kept`);
    all = all.concat(msgs);
  }
  all = dedupe(all);
  console.log(`\nacross all exports      → ${all.length} unique (duplicates collapsed)\n`);

  const profile = voiceProfile(all);
  console.log("voice profile");
  console.log(`  messages          ${profile.messages}`);
  console.log(`  avg words/message ${profile.avgWords}`);
  console.log(`  questions         ${profile.questionShare}%`);
  console.log(`  imperatives       ${profile.imperativeShare}% (make/build/fix/show…)`);
  console.log(`  favourite words   ${profile.favourites.join("  ")}`);
  console.log(`  longest thought   "${profile.sample}"`);
  console.log("\nThe machine's replies were never loaded. Only the person survives.");
}

if (process.argv.includes("--demo")) {
  demo();
} else {
  console.log("Run:  node main.mjs --demo");
}
