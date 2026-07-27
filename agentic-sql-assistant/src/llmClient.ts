/**
 * llmClient - the single seam between the agent loop and any LLM provider.
 *
 * The agent depends ONLY on this interface. To plug in a real model
 * (Gemini, OpenAI, a local model, ...), implement `generate` once and
 * translate these provider-neutral types to/from that provider's function-
 * calling wire format. Nothing else in the agent changes.
 *
 *   class GeminiLLM  implements LLMClient { async generate(msgs, opts) { ... } }
 *   class OpenAILLM  implements LLMClient { async generate(msgs, opts) { ... } }
 *   class OpenAILLM  implements LLMClient { async generate(msgs, opts) { ... } }
 *
 * `MockLLM` below is a deterministic, offline implementation that emits a
 * scripted sequence of tool calls followed by a final answer, so the whole
 * agent loop runs end-to-end with no API key and no network.
 */

export interface FunctionCall {
  name: string;
  args: Record<string, unknown>;
}

export interface FunctionResponse {
  name: string;
  response: { result?: unknown; error?: string };
}

/** One turn of the conversation, in provider-neutral form. */
export interface LLMMessage {
  role: "user" | "model" | "tool";
  text?: string;
  /** Set on a `model` turn when the model wants to call tools. */
  functionCalls?: FunctionCall[];
  /** Set on a `tool` turn: the results, one per call, order-aligned. */
  functionResponses?: FunctionResponse[];
}

/** JSON-schema-style tool declaration handed to the model. */
export interface ToolSchema {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface GenerateOptions {
  /** System prompt / instruction. */
  systemPrompt?: string;
  /**
   * Tools the model may call THIS turn. When the agent is past its soft
   * deadline it deliberately passes `undefined` (tools dropped) to force the
   * model to answer now instead of starting another tool round.
   */
  tools?: ToolSchema[];
  /** Reasoning budget. The agent lowers this to "low" past the deadline. */
  thinkingLevel?: "low" | "high";
}

export interface LLMResponse {
  text?: string;
  functionCalls?: FunctionCall[];
}

export interface LLMClient {
  generate(messages: LLMMessage[], options: GenerateOptions): Promise<LLMResponse>;
}

// ---------------------------------------------------------------------------
// Transcript helpers (useful for real adapters and for scripted mock answers)
// ---------------------------------------------------------------------------

/** The most recent user question in a transcript. */
export function latestUserText(messages: LLMMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user" && messages[i].text) return messages[i].text as string;
  }
  return "";
}

/** The function responses produced by the LAST tool turn, in call order. */
export function lastToolTurnResults(messages: LLMMessage[]): FunctionResponse[] {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "tool" && messages[i].functionResponses) {
      return messages[i].functionResponses as FunctionResponse[];
    }
  }
  return [];
}

// ---------------------------------------------------------------------------
// MockLLM - deterministic, offline, scripted
// ---------------------------------------------------------------------------

type ScriptStep =
  | { call: FunctionCall[] }
  | { final: (messages: LLMMessage[]) => string };

export interface MockScript {
  /** Lowercased substring matched against the latest user question. */
  match: string;
  /**
   * One step per tool round. A `call` step returns function calls (one entry
   * per parallel call in that round); a `final` step returns the answer text.
   */
  steps: ScriptStep[];
}

/**
 * A fully deterministic LLM stand-in.
 *
 * It picks a script by matching the latest user question, then returns the step
 * for the current round. The round is derived from the transcript itself
 * (number of prior `model` turns), so MockLLM holds no mutable per-call cursor
 * and is safe to reuse across independent conversations.
 *
 * It also honours deadline degradation: if the agent drops the tools (passes
 * no `tools`), MockLLM returns a final answer immediately rather than another
 * tool call - exactly what a real model does when tools are withheld.
 */
export class MockLLM implements LLMClient {
  private readonly scripts: MockScript[];
  private readonly degraded: (messages: LLMMessage[]) => string;

  constructor(
    scripts: MockScript[],
    degraded?: (messages: LLMMessage[]) => string,
  ) {
    this.scripts = scripts;
    this.degraded =
      degraded ?? (() => "Here is a quick summary based on what I have so far.");
  }

  async generate(
    messages: LLMMessage[],
    options: GenerateOptions,
  ): Promise<LLMResponse> {
    // Tools were withheld (agent past its soft deadline) -> answer now.
    if (!options.tools || options.tools.length === 0) {
      return { text: this.degraded(messages) };
    }

    const question = latestUserText(messages).toLowerCase();
    const round = messages.filter((m) => m.role === "model").length;
    const script = this.scripts.find((s) => question.includes(s.match));
    const step = script?.steps[round];

    if (!step) {
      return {
        text: "I don't have enough to answer that precisely. Try narrowing the question.",
      };
    }
    if ("call" in step) return { functionCalls: step.call };
    return { text: step.final(messages) };
  }
}
