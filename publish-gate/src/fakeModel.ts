/**
 * The generator, behind a clean interface.
 *
 * In production a hosted language model sits behind DigestGenerator: the
 * request goes out over the network, the copy comes back, and the service
 * reports its own numbers alongside the prose.
 *
 * FAKED FOR THIS DEMO. FakeDigestGenerator is a deterministic stand-in with no
 * network access, no key and no account, so the project runs offline and
 * produces identical output on every run. Swapping in a real client means
 * implementing this one interface; nothing downstream of it changes, because
 * nothing downstream of it trusts what it returns.
 */

import {
  DATASET,
  addDays,
  asOfCollected,
  brandWindowDistinct,
  brandWindowPlacements,
  marketsForBrand,
  sampleListingIds,
  type Brand,
  type Window,
} from './data.js';
import type { Edition } from './editions.js';

export interface DigestRequest {
  window: Window;
  leadBrand: Brand;
  secondBrand: Brand;
  /** The collection cutoff the generator was given when it wrote the copy. */
  writtenOn: string;
}

export interface GeneratedDigest {
  modelId: string;
  copy: string;
  /**
   * The generator's own account of the numbers in its copy. Recorded for the
   * audit trail and never used by the gate: every figure is recomputed from the
   * dataset instead.
   */
  claimedNumbers: Readonly<Record<string, number>>;
  citedListingIds: readonly string[];
}

export interface DigestGenerator {
  generate(request: DigestRequest): GeneratedDigest;
}

export class FakeDigestGenerator implements DigestGenerator {
  readonly modelId = 'offline-stub-v1';

  generate(request: DigestRequest): GeneratedDigest {
    // The generator only ever sees the data collected up to the day it writes,
    // which is exactly why its figures sit below a later recomputation.
    const visible = asOfCollected(DATASET, request.writtenOn);
    const count = brandWindowDistinct(visible, request.leadBrand, request.window);
    const markets = marketsForBrand(visible, request.leadBrand, request.window);
    const m1 = markets[0] ?? 'Portugal';
    const m2 = markets[1] ?? m1;
    const m3 = marketsForBrand(visible, request.secondBrand, request.window)[0] ?? m1;

    const copy = [
      'Market Activity Digest, ' +
        request.window.id +
        ' (' +
        request.window.start +
        ' to ' +
        request.window.end +
        ').',
      request.leadBrand +
        ' added ' +
        count +
        ' new listings across markets including ' +
        m1 +
        ' and ' +
        m2 +
        '.',
      request.secondBrand + ' stayed active in ' + m3 + '.',
      'The category keeps drifting towards smaller pack sizes, which buyers appear to reward.',
    ].join(' ');

    return {
      modelId: this.modelId,
      copy,
      // Deliberately the market-level figure, to show the gate ignoring it.
      claimedNumbers: {
        listings_reported: brandWindowPlacements(visible, request.leadBrand, request.window),
      },
      citedListingIds: sampleListingIds(visible, request.leadBrand, request.window, 2),
    };
  }
}

export function toEdition(id: string, request: DigestRequest, digest: GeneratedDigest): Edition {
  return {
    id,
    window: request.window,
    publishedAt: addDays(request.window.end, 1),
    copy: digest.copy,
    citedListingIds: digest.citedListingIds,
    generatorNumbers: digest.claimedNumbers,
    note: 'Written by ' + digest.modelId + ' on ' + request.writtenOn + '.',
  };
}
