'use strict';

/**
 * Share of AI: core scoring logic.
 *
 * Given a set of category questions and an LLM client (see llmClient.js), this
 * module:
 *   1. asks each question through the client (a grounded answer engine),
 *   2. detects tracked-brand mentions in each answer using word-boundary
 *      matching,
 *   3. ranks brands by first appearance in the answer (earlier == better),
 *   4. normalises the grounding citations, and
 *   5. aggregates everything into a per-brand "Share of AI" scoreboard.
 *
 * The module is pure and has no I/O: pass in config, get back plain objects.
 */

// ---------------------------------------------------------------------------
// Brand-mention matching
// ---------------------------------------------------------------------------

/**
 * Build one case-insensitive regex per brand from its name plus aliases.
 *
 * Two details matter:
 *   - Word-boundary anchors (\b ... \b) so a brand token is only counted as a
 *     whole word. This prevents false matches inside a longer, unrelated phrase
 *     (for example the token "Brand A" must NOT match inside "Brand Analytics").
 *   - Variants are sorted longest-first inside the alternation so the most
 *     specific spelling wins when several variants of the same brand overlap.
 */
function buildBrandMatchers(brands) {
  return brands.map((b) => {
    const variants = [b.name, ...(b.aliases || [])]
      .map((v) => String(v).trim())
      .filter(Boolean)
      // Escape regex metacharacters in each variant.
      .map((v) => v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    // Longest first, so e.g. "Brand A Cloud" is matched before "Brand A".
    variants.sort((a, c) => c.length - a.length);
    const pattern = '\\b(?:' + variants.join('|') + ')\\b';
    return { name: b.name, group: b.group || null, regex: new RegExp(pattern, 'gi') };
  });
}

/**
 * Find every tracked brand mentioned in `text`.
 *
 * Returns an array of:
 *   { brand, mention_count, first_index, rank }
 * ordered by first appearance. `first_index` is the character position of the
 * first mention (lower == earlier). `rank` is 1 for the brand that appears
 * first. Brands that are not mentioned are omitted.
 */
function findBrandMentions(text, matchers) {
  const source = text || '';
  const results = [];
  for (const m of matchers) {
    m.regex.lastIndex = 0;
    let count = 0;
    let firstIdx = -1;
    let match;
    while ((match = m.regex.exec(source)) !== null) {
      count++;
      if (firstIdx === -1) firstIdx = match.index;
      // Guard against zero-length matches looping forever.
      if (match.index === m.regex.lastIndex) m.regex.lastIndex++;
    }
    if (count > 0) {
      results.push({ brand: m.name, mention_count: count, first_index: firstIdx });
    }
  }
  // Rank by first-mention position; rank 1 = appears first.
  results.sort((a, b) => a.first_index - b.first_index);
  results.forEach((r, i) => { r.rank = i + 1; });
  return results;
}

// ---------------------------------------------------------------------------
// Citations
// ---------------------------------------------------------------------------

/**
 * Normalise the client's citations into { url, domain, title } and drop exact
 * duplicate URLs. The client returns { title, url }; the domain is derived here.
 */
function normalizeCitations(citations) {
  const seen = new Set();
  const out = [];
  for (const c of citations || []) {
    const url = (c && c.url) || '';
    if (!url || seen.has(url)) continue;
    seen.add(url);
    let domain = '';
    try { domain = new URL(url).hostname.replace(/^www\./, ''); } catch (_) { domain = ''; }
    out.push({ url, domain, title: (c && c.title) || '' });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Per-answer analysis
// ---------------------------------------------------------------------------

/**
 * Analyse a single grounded answer against the brand matchers.
 * Returns the ranked brand list, normalised citations, and the total mention
 * count across all tracked brands.
 */
function analyzeAnswer(answer, matchers) {
  const text = (answer && answer.text) || '';
  const brands = findBrandMentions(text, matchers);
  const citations = normalizeCitations(answer && answer.citations);
  const totalMentions = brands.reduce((s, b) => s + b.mention_count, 0);
  return { brands, citations, total_brand_mentions: totalMentions };
}

// ---------------------------------------------------------------------------
// Work list (query x market expansion)
// ---------------------------------------------------------------------------

/**
 * Expand the query config into a flat list of (query, market) jobs. Global
 * queries produce one job; per-market queries produce one per market, with
 * {market_label} substituted into the text.
 */
function buildWorkList(queryConfig) {
  const work = [];
  const markets = queryConfig.markets || [];
  for (const q of queryConfig.queries || []) {
    if (q.scope === 'per-market') {
      for (const m of markets) {
        work.push({
          query_id: q.id,
          query_text: q.text.replace('{market_label}', m.label),
          market: m.code,
          dashboard_market_code: m.dashboard_code,
          topic: q.topic,
          journey_stage: q.journey,
          audience: q.audience
        });
      }
    } else {
      work.push({
        query_id: q.id,
        query_text: q.text,
        market: 'GLOBAL',
        dashboard_market_code: 'GLOBAL',
        topic: q.topic,
        journey_stage: q.journey,
        audience: q.audience
      });
    }
  }
  return work;
}

// ---------------------------------------------------------------------------
// Scoreboard
// ---------------------------------------------------------------------------

/**
 * Aggregate per-answer results into a per-brand "Share of AI" scoreboard.
 *
 * The headline metric is a first-appearance-weighted score. Each time a brand
 * appears in an answer it earns 1 / rank points, so being named first is worth
 * more than being named last. Each brand's Share of AI is its points as a
 * percentage of all brands' points across every answer.
 *
 * Also reported per brand:
 *   - appearances     : answers the brand was mentioned in
 *   - visibility_pct  : appearances / total answers
 *   - total_mentions  : raw mention count across all answers
 *   - mention_share_pct: mentions / all mentions
 *   - avg_rank        : mean rank across the answers it appeared in
 */
function computeScoreboard(rows, brands) {
  const stats = new Map();
  for (const b of brands) {
    stats.set(b.name, {
      brand: b.name,
      group: b.group || null,
      appearances: 0,
      total_mentions: 0,
      rank_points: 0,
      rank_sum: 0
    });
  }

  let totalMentionsAll = 0;
  for (const row of rows) {
    for (const bm of (row.brands_mentioned || [])) {
      const s = stats.get(bm.brand);
      if (!s) continue;
      s.appearances += 1;
      s.total_mentions += bm.mention_count;
      s.rank_points += 1 / bm.rank;
      s.rank_sum += bm.rank;
      totalMentionsAll += bm.mention_count;
    }
  }

  const totalRankPoints = Array.from(stats.values()).reduce((sum, s) => sum + s.rank_points, 0);
  const totalAnswers = rows.length;

  const scoreboard = Array.from(stats.values()).map((s) => ({
    brand: s.brand,
    group: s.group,
    appearances: s.appearances,
    visibility_pct: totalAnswers ? round1((s.appearances / totalAnswers) * 100) : 0,
    total_mentions: s.total_mentions,
    mention_share_pct: totalMentionsAll ? round1((s.total_mentions / totalMentionsAll) * 100) : 0,
    avg_rank: s.appearances ? round2(s.rank_sum / s.appearances) : null,
    share_of_ai_pct: totalRankPoints ? round1((s.rank_points / totalRankPoints) * 100) : 0
  }));

  // Best Share of AI first.
  scoreboard.sort((a, b) => b.share_of_ai_pct - a.share_of_ai_pct);
  return scoreboard;
}

function round1(n) { return Math.round(n * 10) / 10; }
function round2(n) { return Math.round(n * 100) / 100; }

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

/**
 * Run the full pipeline over an LLM client.
 *
 * @param {object} client       - an LLMClient with async ask(question).
 * @param {object} queryConfig  - { markets, queries } (see config/queries.json).
 * @param {object} brandConfig  - { brands } (see config/brands.json).
 * @param {string} [snapshotDate] - ISO date stamp for the run (defaults today).
 * @returns {Promise<{ snapshot_date, rows, scoreboard, errors }>}
 */
async function runShareOfAi(client, queryConfig, brandConfig, snapshotDate) {
  const date = snapshotDate || new Date().toISOString().slice(0, 10);
  const matchers = buildBrandMatchers(brandConfig.brands);
  const anchor = brandConfig.anchor || null;
  const work = buildWorkList(queryConfig);

  const rows = [];
  const errors = [];

  for (const w of work) {
    try {
      const answer = await client.ask(w.query_text);
      const { brands, citations, total_brand_mentions } = analyzeAnswer(answer, matchers);
      const anchorHit = anchor ? brands.find((b) => b.brand === anchor) : null;
      rows.push({
        snapshot_date: date,
        query_id: w.query_id,
        query_text: w.query_text,
        market: w.market,
        dashboard_market_code: w.dashboard_market_code,
        topic: w.topic,
        journey_stage: w.journey_stage,
        audience: w.audience,
        response_text: answer.text || '',
        brands_mentioned: brands,
        citations,
        anchor_brand: anchor,
        anchor_rank: anchorHit ? anchorHit.rank : null,
        anchor_mentions: anchorHit ? anchorHit.mention_count : 0,
        total_brand_mentions,
        anchor_share_pct: total_brand_mentions > 0 && anchorHit
          ? round1((anchorHit.mention_count / total_brand_mentions) * 100)
          : 0
      });
    } catch (err) {
      errors.push({ query_id: w.query_id, market: w.market, error: err.message });
    }
  }

  const scoreboard = computeScoreboard(rows, brandConfig.brands);
  return { snapshot_date: date, rows, scoreboard, errors };
}

module.exports = {
  buildBrandMatchers,
  findBrandMentions,
  normalizeCitations,
  analyzeAnswer,
  buildWorkList,
  computeScoreboard,
  runShareOfAi
};
