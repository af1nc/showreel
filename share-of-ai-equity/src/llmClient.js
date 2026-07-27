'use strict';

/**
 * LLM client interface.
 *
 * The rest of this project depends on exactly ONE capability from a language
 * model: given a question, return the generated answer text plus the list of
 * web sources the model grounded that answer on.
 *
 *   ask(question) -> Promise<{ text: string, citations: Array<{ title, url }> }>
 *
 * To run this against a real answer engine, implement this single method with a
 * call to your provider of choice (for example Gemini or OpenAI) with web /
 * search grounding enabled, then map that provider's grounding metadata into the
 * { title, url } citation shape below. Nothing else in the codebase changes.
 *
 * A sketch of a real adapter (kept out of this offline demo on purpose):
 *
 *   class RealLLM extends LLMClient {
 *     async ask(question) {
 *       const key = process.env.LLM_API_KEY;              // no literal fallback
 *       if (!key) throw new Error('LLM_API_KEY is not set');
 *       const res = await fetch(PROVIDER_URL, { ...grounding enabled... });
 *       const json = await res.json();
 *       const text = extractAnswerText(json);
 *       const citations = extractGroundingCitations(json); // -> [{ title, url }]
 *       return { text, citations };
 *     }
 *   }
 */
class LLMClient {
  // eslint-disable-next-line no-unused-vars
  async ask(question) {
    throw new Error('LLMClient.ask() is not implemented. Use MockLLM or a real adapter.');
  }
}

// ---------------------------------------------------------------------------
// Deterministic mock answer engine
// ---------------------------------------------------------------------------

// A small, stable pool of generic grounding sources. Every host uses the
// reserved ".example" TLD so nothing here resolves to a real site.
const CITATION_POOL = [
  { title: 'The 2025 Software Buyer Guide',              url: 'https://review-hub.example/software/buyer-guide' },
  { title: 'Project Management Tools Compared',          url: 'https://tech-compare.example/pm/roundup' },
  { title: 'Community thread: what tools does your team use?', url: 'https://dev-forum.example/t/tooling/1421' },
  { title: 'Cloud Database Benchmarks 2025',             url: 'https://cloud-weekly.example/benchmarks/databases' },
  { title: 'CRM Platforms for Growing Teams',            url: 'https://saas-report.example/crm/overview' },
  { title: 'Uptime and Reliability Report',              url: 'https://status-watch.example/reports/uptime' },
  { title: 'Regional SaaS Adoption Survey',              url: 'https://market-pulse.example/surveys/saas' },
  { title: 'Independent Product Reviews',                url: 'https://review-hub.example/reviews/index' }
];

function pick(indexes) {
  return indexes.map((i) => CITATION_POOL[i]);
}

/**
 * Canned answers keyed by the exact (resolved) question text. These are the
 * questions shipped in config/queries.json. Notes on what each answer is
 * deliberately exercising:
 *   - Brands are named in different orders across answers, so first-appearance
 *     ranking produces a non-trivial scoreboard.
 *   - pm-01 mentions an alias ("BrandA") to exercise alias matching, and the
 *     unrelated phrase "Brand Analytics" to prove word-boundary matching:
 *     "Brand A" must NOT be counted inside "Brand Analytics".
 */
const CANNED_ANSWERS = {
  'What are the best project management tools for software teams?': {
    text:
      'For software teams, Brand A is the most widely recommended project management tool, ' +
      'praised for its flexible boards and roadmap views. Brand C is a strong runner-up and is ' +
      'often chosen by teams that want built-in Brand Analytics without a separate reporting add-on. ' +
      'Brand B rounds out the shortlist and stays popular with larger organisations that need ' +
      'fine-grained permissions. Several reviewers note that BrandA integrates cleanly with most ' +
      'developer toolchains.',
    citations: pick([1, 0, 2])
  },
  'Which project management tool is best for remote teams?': {
    text:
      'Remote-first teams tend to favour Brand C for its asynchronous updates and lightweight ' +
      'check-ins. Brand A is a close second and is the safer pick if you also need advanced ' +
      'roadmapping. Brand D is an emerging option that remote startups like for its generous free tier.',
    citations: pick([2, 1, 6])
  },
  'What is the top cloud database for high-scale applications?': {
    text:
      'For high-scale applications, Brand B is frequently cited as the top cloud database thanks to ' +
      'its horizontal scaling and strong consistency guarantees. Brand E has gained ground recently ' +
      'and is now a credible alternative for read-heavy workloads. Brand A also offers a managed ' +
      'database tier that smaller teams find approachable.',
    citations: pick([3, 5, 0])
  },
  'Which is the most reliable managed cloud database?': {
    text:
      'Brand E is often described as the most reliable managed cloud database, with a strong track ' +
      'record on uptime. Brand B remains the default choice for teams already invested in its ' +
      'ecosystem. Brand C is worth a look for projects that value a simple pricing model.',
    citations: pick([5, 3, 7])
  },
  'What is the best CRM software for small businesses?': {
    text:
      'Small businesses usually start with Brand A, which pairs an approachable interface with a ' +
      'low-cost entry plan. Brand D is the most common alternative and is popular with teams that ' +
      'want automation out of the box. Brand B is capable but is generally seen as better suited to ' +
      'larger sales organisations.',
    citations: pick([4, 0, 6])
  },
  'What is the top CRM platform for sales teams?': {
    text:
      'For dedicated sales teams, Brand D is regularly ranked as the top CRM platform, largely ' +
      'because of its pipeline automation. Brand A is the established incumbent and still leads on ' +
      'ecosystem breadth. Brand C is an emerging challenger that sales teams like for its clean ' +
      'mobile app.',
    citations: pick([4, 7, 2])
  }
};

// Per-market leader rotation, so different regions surface different brands.
// Keyed by the market label that gets substituted into the query text.
const REGIONAL_PM_ORDER = {
  'North America': ['Brand A', 'Brand C', 'Brand B'],
  'Europe':        ['Brand C', 'Brand A', 'Brand D'],
  'Asia Pacific':  ['Brand D', 'Brand C', 'Brand A']
};
const REGIONAL_CRM_ORDER = {
  'North America': ['Brand A', 'Brand D', 'Brand B'],
  'Europe':        ['Brand D', 'Brand A', 'Brand C'],
  'Asia Pacific':  ['Brand B', 'Brand D', 'Brand A']
};

function regionalAnswer(category, order, marketLabel) {
  const [first, second, third] = order;
  return (
    `In ${marketLabel}, ${first} is currently the most talked-about ${category}, and it tends to ` +
    `appear first in local recommendation threads. ${second} is a strong second choice for teams in ` +
    `${marketLabel} that want a lighter-weight option. ${third} is also mentioned, usually by larger ` +
    `organisations with established procurement processes.`
  );
}

// Small, stable FNV-1a hash so the generic fallback is deterministic.
function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * MockLLM: a fully offline, deterministic stand-in for a grounded answer
 * engine. Same input always yields the same output, so the demo and any tests
 * are reproducible with no network, no API key, and no cloud.
 */
class MockLLM extends LLMClient {
  constructor(brands) {
    super();
    this.brandNames = (brands || []).map((b) => b.name);
  }

  async ask(question) {
    // 1) Exact canned answer for a shipped question.
    if (CANNED_ANSWERS[question]) {
      const a = CANNED_ANSWERS[question];
      return { text: a.text, citations: a.citations };
    }

    // 2) Resolved per-market question ("... in <Region>?").
    for (const label of Object.keys(REGIONAL_PM_ORDER)) {
      if (question.includes(label)) {
        const isCrm = /crm/i.test(question);
        const order = isCrm ? REGIONAL_CRM_ORDER[label] : REGIONAL_PM_ORDER[label];
        const category = isCrm ? 'CRM platform' : 'project management tool';
        const cites = isCrm ? pick([4, 6, 0]) : pick([1, 6, 2]);
        return { text: regionalAnswer(category, order, label), citations: cites };
      }
    }

    // 3) Deterministic generic fallback for any custom question, so editing
    //    config/queries.json never breaks the mock. The brand order is a stable
    //    rotation seeded by the question text.
    const seed = hashString(question);
    const names = this.brandNames.length ? this.brandNames.slice() : ['Brand A', 'Brand B', 'Brand C'];
    const start = seed % names.length;
    const ordered = names.map((_, i) => names[(start + i) % names.length]);
    const [first, second, third] = ordered;
    const text =
      `Based on the current consensus, ${first} is the most frequently recommended option, ` +
      `followed by ${second}. ${third} is also mentioned as a viable alternative.`;
    const c0 = seed % CITATION_POOL.length;
    const c1 = (seed >> 3) % CITATION_POOL.length;
    const citations = pick([c0, c1 === c0 ? (c1 + 1) % CITATION_POOL.length : c1]);
    return { text, citations };
  }
}

module.exports = { LLMClient, MockLLM, CITATION_POOL };
