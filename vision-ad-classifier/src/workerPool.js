'use strict';

/**
 * workerPool.js
 *
 * A bounded-concurrency worker pool. Runs `worker(item, index)` over `items`
 * with at most `concurrency` tasks in flight at once, returning results in the
 * original input order.
 *
 * This matters for classifying many creatives: firing an unbounded number of
 * simultaneous model calls is exactly how you get rate-limited. A small fixed
 * pool keeps throughput high while staying under provider quotas.
 */

/**
 * @param {Array<any>} items
 * @param {(item:any, index:number) => Promise<any>} worker
 * @param {object} [opts]
 * @param {number} [opts.concurrency=5]
 * @param {(done:number, total:number, result:any, index:number) => void} [opts.onProgress]
 * @returns {Promise<Array<any>>} results aligned to `items` order
 */
async function runPool(items, worker, opts = {}) {
  const concurrency = Math.max(1, opts.concurrency || 5);
  const results = new Array(items.length);
  let next = 0;
  let completed = 0;

  async function runOne() {
    // Each virtual worker pulls the next index until the queue is drained.
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      try {
        results[i] = await worker(items[i], i);
      } catch (err) {
        results[i] = { error: err && err.message ? err.message.slice(0, 120) : String(err) };
      }
      completed += 1;
      if (opts.onProgress) opts.onProgress(completed, items.length, results[i], i);
    }
  }

  const size = Math.min(concurrency, items.length || 1);
  await Promise.all(Array.from({ length: size }, () => runOne()));
  return results;
}

module.exports = { runPool };
