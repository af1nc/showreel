// Anchor colours for the diverging scale, as [r, g, b] triples.
const RED = [220, 38, 38] as const; // low end
const AMBER = [234, 179, 8] as const; // the centre
const GREEN = [22, 163, 74] as const; // high end
const NEUTRAL = "rgb(63, 63, 70)"; // null / zero / not measured

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + t * (b - a));
}

/**
 * Diverging colour scale anchored at a RUNTIME centre rather than a fixed
 * midpoint.
 *
 * Anchoring at a value known only at runtime (a break-even point, a median,
 * a target) is what stops one large outlier from washing the whole scale to a
 * single hue.
 *
 *   value <= 0 or not finite  ->  neutral grey ("not measured" is not "bad")
 *   0 .. center               ->  red  -> amber   (t = value / center)
 *   center .. 3 * center      ->  amber -> green   (t clamped to 1)
 *
 * Both legs are plain per-channel RGB linear interpolations.
 */
export function getDivergingColor(
  value: number | null | undefined,
  center: number,
): string {
  if (value == null || !isFinite(value) || value <= 0) return NEUTRAL;
  const c = center > 0 ? center : 1;

  if (value < c) {
    const t = value / c; // 0 -> 1 across the lower leg
    return `rgb(${lerp(RED[0], AMBER[0], t)}, ${lerp(RED[1], AMBER[1], t)}, ${lerp(
      RED[2],
      AMBER[2],
      t,
    )})`;
  }

  const t = Math.min((value - c) / (2 * c), 1); // center -> 3 * center
  return `rgb(${lerp(AMBER[0], GREEN[0], t)}, ${lerp(AMBER[1], GREEN[1], t)}, ${lerp(
    AMBER[2],
    GREEN[2],
    t,
  )})`;
}

interface DivergingScaleProps {
  /** The runtime centre the scale diverges around. */
  center?: number;
}

// A generic set of cell values, including a null to show the neutral fallback.
const DEMO_VALUES: Array<number | null> = [
  0.2, 0.5, 0.8, 1.0, 1.3, 1.6, 1.9, 2.2, 2.6, 3.0, null, 0.0,
];

export function DivergingScale({ center = 1.0 }: DivergingScaleProps) {
  return (
    <div className="ds-wrap">
      <div className="ds-grid">
        {DEMO_VALUES.map((v, i) => (
          <div
            key={i}
            className="ds-cell"
            style={{ background: getDivergingColor(v, center) }}
            title={v == null ? "no value" : `value ${v}`}
          >
            {v == null ? "n/a" : v.toFixed(1)}
          </div>
        ))}
      </div>
      <div className="ds-legend">
        <span className="ds-swatch" style={{ background: `rgb(${RED.join(",")})` }} />
        <span className="ds-legend-label">below centre</span>
        <span className="ds-swatch" style={{ background: `rgb(${AMBER.join(",")})` }} />
        <span className="ds-legend-label">centre = {center.toFixed(1)}</span>
        <span className="ds-swatch" style={{ background: `rgb(${GREEN.join(",")})` }} />
        <span className="ds-legend-label">3x centre and up</span>
        <span className="ds-swatch" style={{ background: NEUTRAL }} />
        <span className="ds-legend-label">no value</span>
      </div>
    </div>
  );
}
