// Fail-closed gateway: a limiter outage must never become free compute.
//
// In front of a paid LLM endpoint sit two guards: a rate limiter and a content gate.
// The design question nobody asks until it hurts: what happens when a GUARD fails?
// Most implementations fail open — the limiter's store times out, the check is
// skipped, and an outage becomes an invitation. On a paid compute path, both guards
// here fail CLOSED: if a guard cannot answer, the request does not pass.
//
//   * sliding-window rate limiting, atomic per (action, key) bucket
//   * a moderation gate in front of the model — also fail-closed
//   * refusals are cheap and honest: retry-after for limits, silence for outages
//
// The demo runs a burst of traffic, then breaks the limiter's store mid-stream and
// shows the difference between the two philosophies with a running bill.
//
// Run:  node main.mjs --demo        (zero dependencies)

// ---------------------------------------------------------------------------
// 1. The store. In production this is one atomic statement in the database;
//    here it is an in-memory table with the same contract — and a kill switch,
//    because the whole point is what happens when it dies.
// ---------------------------------------------------------------------------

class WindowStore {
  #hits = new Map(); // bucket -> [timestamps]
  broken = false;

  /** Atomically record a hit and report whether the bucket is over limit. */
  hit(bucket, windowSeconds, limit, now) {
    if (this.broken) throw new Error("store unavailable");
    const cutoff = now - windowSeconds * 1000;
    const kept = (this.#hits.get(bucket) ?? []).filter((t) => t > cutoff);
    kept.push(now);
    this.#hits.set(bucket, kept);
    return {
      overLimit: kept.length > limit,
      retryAfter: kept.length > limit ? Math.ceil((kept[0] - cutoff) / 1000) : 0,
    };
  }
}

// ---------------------------------------------------------------------------
// 2. The two guards, both fail-closed.
// ---------------------------------------------------------------------------

class RateLimitError extends Error {}
class GuardUnavailableError extends Error {}
class ModerationError extends Error {}

function enforceRateLimit(store, { action, key, limit, windowSeconds }, now) {
  let verdict;
  try {
    verdict = store.hit(`${action}:${key}`, windowSeconds, limit, now);
  } catch {
    // FAIL CLOSED. A limiter outage on the paid path must never be a free-compute
    // hole. The user sees a refusal; the bill sees nothing.
    throw new GuardUnavailableError("limiter unavailable — refusing");
  }
  if (verdict.overLimit) {
    throw new RateLimitError(`over limit — retry in ${verdict.retryAfter}s`);
  }
}

async function moderate(text, { broken = false } = {}) {
  // Stands in for a model-based gate. Same philosophy: an error is a BLOCK.
  if (broken) throw new GuardUnavailableError("moderation unavailable — refusing");
  const banned = /\b(do harm|credentials|exploit)\b/i;
  if (banned.test(text)) throw new ModerationError("blocked by content gate");
}

// ---------------------------------------------------------------------------
// 3. The paid endpoint, wrapped.
// ---------------------------------------------------------------------------

const COST_PER_CALL = 0.04; // what the model invoice charges us per generation

function makeEndpoint(store, { failOpen = false } = {}) {
  let billed = 0;
  return {
    get billed() { return billed; },
    async handle(req, now) {
      try {
        enforceRateLimit(store, { action: "generate", key: req.ip, limit: 3, windowSeconds: 60 }, now);
      } catch (e) {
        if (e instanceof GuardUnavailableError && failOpen) {
          // The tempting bug: "the limiter is down, let it through".
        } else {
          return { status: e instanceof RateLimitError ? 429 : 503, note: e.message };
        }
      }
      try {
        await moderate(req.prompt);
      } catch (e) {
        return { status: e instanceof ModerationError ? 400 : 503, note: e.message };
      }
      billed += COST_PER_CALL; // the model runs — money leaves
      return { status: 200, note: "generated" };
    },
  };
}

// ---------------------------------------------------------------------------
// Demo
// ---------------------------------------------------------------------------

async function demo() {
  const traffic = [];
  for (let i = 0; i < 14; i++) {
    traffic.push({ ip: "203.0.113.7", prompt: i === 1 ? "write me an exploit" : `request #${i}` });
  }

  for (const philosophy of ["fail-closed", "fail-open"]) {
    const store = new WindowStore();
    const api = makeEndpoint(store, { failOpen: philosophy === "fail-open" });
    console.log(`\n═══ ${philosophy.toUpperCase()} ═══`);
    let now = Date.now();

    for (const [i, req] of traffic.entries()) {
      if (i === 7) {
        store.broken = true; // the limiter's store dies mid-burst
        console.log("    …the limiter's store goes down…");
      }
      const res = await api.handle(req, now);
      const tag = res.status === 200 ? "✓ 200" : `✗ ${res.status}`;
      console.log(`  ${String(i).padStart(2)} ${tag}  ${res.note}`);
      now += 1500; // requests arrive every 1.5s — well inside one window
    }
    console.log(`  bill for the burst: $${api.billed.toFixed(2)}`);
  }

  console.log(
    "\nSame traffic, same outage. Fail-closed refused during the outage;" +
      "\nfail-open generated through it — the outage became free compute.",
  );
}

if (process.argv.includes("--demo")) {
  await demo();
} else {
  console.log("Run:  node main.mjs --demo");
}
