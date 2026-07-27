/**
 * agent - a raw ReAct-style tool-calling loop over an {@link LLMClient}.
 *
 * No orchestration framework. The whole agent is this one bounded loop:
 *
 *   while not done and under the round cap:
 *     ask the model (with tools, unless we are past the soft deadline)
 *     if it returned tool calls -> run them ALL in parallel, feed results back
 *     else -> that text is the answer
 *
 * Four ideas make it production-shaped:
 *
 *   1. Bounded loop (MAX_TOOL_ROUNDS). A runaway model can never loop forever.
 *   2. Parallel tool execution within a round. When the model issues several
 *      independent calls in one turn they run concurrently (Promise.all) and
 *      results are fed back in the SAME order the model asked for them.
 *   3. Soft-deadline degradation. Past a time budget we drop the tools and
 *      lower the reasoning level, forcing the model to answer with what it has
 *      instead of hanging mid-investigation.
 *   4. Volatile-vs-stable answer cache. Answers are cached by a normalized
 *      question hash - but ONLY when no volatile tool was used, so live numbers
 *      are never served stale.
 */
import { createHash } from "node:crypto";
import type {
  FunctionCall,
  LLMClient,
  LLMMessage,
} from "./llmClient";
import type { Toolset } from "./tools";

export const MAX_TOOL_ROUNDS = 14;
export const SOFT_DEADLINE_MS = 180_000;

export interface ToolTraceEntry {
  tool: string;
  detail: string;
  ms: number;
  error?: string;
}

// ---------------------------------------------------------------------------
// Answer cache
// ---------------------------------------------------------------------------

export interface AnswerCache {
  get(question: string): Promise<string | null>;
  put(question: string, reply: string, tools: string[]): Promise<void>;
}

/** Normalize a question so trivially-different phrasings share a cache key. */
export function normQuestion(q: string): string {
  return q
    .toLowerCase()
    .replace(/[^\w\s%$.()-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function cacheKeyFor(q: string): string {
  return "q_" + createHash("sha256").update(normQuestion(q)).digest("hex").slice(0, 40);
}

/**
 * A tiny in-memory cache. Swap for Redis / a document store / SQLite by
 * implementing the same {@link AnswerCache} interface - nothing else changes.
 */
export class InMemoryAnswerCache implements AnswerCache {
  private readonly store = new Map<string, { reply: string; cachedAt: number }>();

  constructor(private readonly maxAgeMs = 8 * 24 * 60 * 60 * 1000) {}

  async get(question: string): Promise<string | null> {
    const hit = this.store.get(cacheKeyFor(question));
    if (!hit) return null;
    if (Date.now() - hit.cachedAt > this.maxAgeMs) return null;
    return hit.reply;
  }

  async put(question: string, reply: string): Promise<void> {
    this.store.set(cacheKeyFor(question), { reply, cachedAt: Date.now() });
  }

  size(): number {
    return this.store.size;
  }
}

// ---------------------------------------------------------------------------
// Agent
// ---------------------------------------------------------------------------

export type RoundInfo =
  | { round: number; kind: "tools"; overDeadline: boolean; calls: FunctionCall[] }
  | { round: number; kind: "final"; overDeadline: boolean; text: string };

export interface AgentOptions {
  llm: LLMClient;
  toolset: Toolset;
  systemPrompt: string;
  maxToolRounds?: number;
  softDeadlineMs?: number;
  cache?: AnswerCache;
  /** Injectable clock, for deterministic tests. Defaults to Date.now. */
  now?: () => number;
  /** Optional observer for step-by-step tracing (used by the demo). */
  onRound?: (info: RoundInfo) => void;
}

export interface AgentResult {
  reply: string;
  toolTrace: ToolTraceEntry[];
  cached: boolean;
}

export class Agent {
  private readonly llm: LLMClient;
  private readonly toolset: Toolset;
  private readonly systemPrompt: string;
  private readonly maxToolRounds: number;
  private readonly softDeadlineMs: number;
  private readonly cache?: AnswerCache;
  private readonly now: () => number;
  private readonly onRound?: (info: RoundInfo) => void;

  constructor(opts: AgentOptions) {
    this.llm = opts.llm;
    this.toolset = opts.toolset;
    this.systemPrompt = opts.systemPrompt;
    this.maxToolRounds = opts.maxToolRounds ?? MAX_TOOL_ROUNDS;
    this.softDeadlineMs = opts.softDeadlineMs ?? SOFT_DEADLINE_MS;
    this.cache = opts.cache;
    this.now = opts.now ?? Date.now;
    this.onRound = opts.onRound;
  }

  /** Answer a standalone question, consulting/populating the cache. */
  async ask(question: string): Promise<AgentResult> {
    if (this.cache) {
      const hit = await this.cache.get(question);
      if (hit) {
        return {
          reply: hit,
          toolTrace: [{ tool: "cache", detail: "instant (pre-computed answer)", ms: 0 }],
          cached: true,
        };
      }
    }

    const { reply, toolTrace } = await this.computeAnswer(question);

    // Cache ONLY stable answers: no volatile tool was used, and it is a real
    // answer. Live numbers (run_sql) are therefore never served from cache.
    if (this.cache && this.isCacheable(reply, toolTrace)) {
      await this.cache.put(question, reply, toolTrace.map((t) => t.tool));
    }

    return { reply, toolTrace, cached: false };
  }

  private isCacheable(reply: string, toolTrace: ToolTraceEntry[]): boolean {
    if (toolTrace.some((t) => this.toolset.isVolatile(t.tool))) return false;
    if (/couldn't produce an answer|Answered quickly to stay responsive/.test(reply)) {
      return false;
    }
    return true;
  }

  /** The core tool loop. No persistence, no cache - pure compute. */
  private async computeAnswer(
    question: string,
  ): Promise<{ reply: string; toolTrace: ToolTraceEntry[] }> {
    const messages: LLMMessage[] = [{ role: "user", text: question }];
    const toolTrace: ToolTraceEntry[] = [];
    const startedAt = this.now();
    let reply = "";

    for (let round = 0; round <= this.maxToolRounds; round++) {
      const overDeadline = this.now() - startedAt > this.softDeadlineMs;

      const response = await this.llm.generate(messages, {
        systemPrompt: this.systemPrompt,
        // Past the deadline: drop the tools and lower the reasoning budget so
        // the model answers immediately instead of starting another round.
        tools: overDeadline ? undefined : this.toolset.schemas,
        thinkingLevel: overDeadline ? "low" : "high",
      });

      const functionCalls = overDeadline ? [] : response.functionCalls ?? [];

      if (functionCalls.length === 0 || round === this.maxToolRounds) {
        reply = (response.text ?? "").trim();
        if (!reply) {
          reply =
            "I couldn't produce an answer for that - try rephrasing or narrowing the question.";
        }
        // Always carry a confidence line, even on the fast (deadline) path.
        if (!/confidence:\s*(high|medium|low)/i.test(reply)) {
          reply +=
            "\n\nConfidence: Medium - answered under a time limit; ask me to dig deeper to confirm.";
        }
        if (overDeadline) {
          reply +=
            "\n\n_(Answered quickly to stay responsive - ask me to dig deeper on any part.)_";
        }
        this.onRound?.({ round, kind: "final", overDeadline, text: reply });
        break;
      }

      this.onRound?.({ round, kind: "tools", overDeadline, calls: functionCalls });

      // Record the model's tool-call turn.
      messages.push({ role: "model", functionCalls });

      // Execute all calls in THIS round concurrently; order is preserved so the
      // responses line up with the calls the model made.
      const settled = await Promise.all(
        functionCalls.map(async (fc) => {
          const started = this.now();
          try {
            const { result, detail } = await this.toolset.execute(fc.name, fc.args);
            return {
              trace: { tool: fc.name, detail, ms: this.now() - started } as ToolTraceEntry,
              response: { name: fc.name, response: { result } },
            };
          } catch (err) {
            const msg = String((err as Error)?.message ?? err).slice(0, 300);
            return {
              trace: {
                tool: fc.name,
                detail: msg,
                ms: this.now() - started,
                error: msg,
              } as ToolTraceEntry,
              response: { name: fc.name, response: { error: msg } },
            };
          }
        }),
      );

      for (const s of settled) toolTrace.push(s.trace);
      messages.push({ role: "tool", functionResponses: settled.map((s) => s.response) });
    }

    return { reply, toolTrace };
  }
}
