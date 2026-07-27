interface ProbabilityGaugeProps {
  /** A probability in the range 0..1. */
  probability: number;
}

// The arc is a semicircle of radius 90, so its length is PI * r ~= 283.
const ARC_LENGTH = 283;

/**
 * A semicircular gauge drawn as a single SVG arc.
 *
 * The fill is not a shape but a stroke trick: the same arc path is drawn twice,
 * once as a grey track and once with a red -> amber -> green gradient. The
 * coloured copy uses strokeDasharray = "<fill> <rest>" so exactly
 * probability * ARC_LENGTH of the stroke is painted and the remainder is a gap.
 * The needle is a straight line rotated from -90deg (empty) to +90deg (full)
 * by -90 + probability * 180 degrees.
 */
export function ProbabilityGauge({ probability }: ProbabilityGaugeProps) {
  const p = Math.min(Math.max(probability, 0), 1);
  const pct = p * 100;
  const rotation = -90 + p * 180;

  return (
    <div className="pg-wrap">
      <div className="pg-svg">
        <svg viewBox="0 0 200 100" className="pg-svg-el">
          <defs>
            <linearGradient id="pgGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#ef4444" />
              <stop offset="40%" stopColor="#f59e0b" />
              <stop offset="60%" stopColor="#f59e0b" />
              <stop offset="100%" stopColor="#22c55e" />
            </linearGradient>
          </defs>

          {/* Track */}
          <path
            d="M 10 95 A 90 90 0 0 1 190 95"
            fill="none"
            stroke="#e5e7eb"
            strokeWidth="12"
            strokeLinecap="round"
          />

          {/* Filled arc, painted with a dash pattern of exactly p * ARC_LENGTH. */}
          <path
            d="M 10 95 A 90 90 0 0 1 190 95"
            fill="none"
            stroke="url(#pgGradient)"
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={`${p * ARC_LENGTH} ${ARC_LENGTH}`}
          />

          {/* Needle */}
          <line
            x1="100"
            y1="95"
            x2="100"
            y2="20"
            stroke="#334155"
            strokeWidth="2.5"
            strokeLinecap="round"
            transform={`rotate(${rotation}, 100, 95)`}
          />
          <circle cx="100" cy="95" r="5" fill="#334155" />

          {/* End labels */}
          <text x="10" y="98" fontSize="10" fill="#94a3b8" textAnchor="start">
            0%
          </text>
          <text x="190" y="98" fontSize="10" fill="#94a3b8" textAnchor="end">
            100%
          </text>
        </svg>
      </div>
      <div className="pg-value">{pct.toFixed(1)}%</div>
    </div>
  );
}
