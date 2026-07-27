import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from "recharts";

// A single observation in the series. Everything is a generic "metric".
export interface CounterfactualPoint {
  /** Category / time label shown on the X axis. */
  date: string;
  /** The actual observed value. */
  value: number;
  /** The predicted counterfactual: what the model expected without any change. */
  predicted: number;
  /** Lower bound of the confidence interval around `predicted`. */
  lower: number;
  /** Upper bound of the confidence interval around `predicted`. */
  upper: number;
}

interface CounterfactualChartProps {
  data: CounterfactualPoint[];
  /** Index into `data` where the intervention happened (draws a reference line). */
  interventionIndex: number;
  title?: string;
}

const COLORS = {
  actual: "#2563eb", // solid observed line
  predicted: "#f59e0b", // dashed counterfactual line and band tint
  intervention: "#ef4444", // reference line at the intervention
  grid: "#94a3b8",
  axis: "#94a3b8",
};

function CounterfactualTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const get = (key: string) =>
    payload.find((p: any) => p.dataKey === key)?.value as number | undefined;
  const actual = get("value");
  const predicted = get("predicted");
  const delta =
    actual != null && predicted != null ? actual - predicted : undefined;

  return (
    <div className="cf-tooltip">
      <div className="cf-tooltip-label">{label}</div>
      <div className="cf-tooltip-row">
        <span className="cf-dot" style={{ background: COLORS.actual }} />
        <span>Actual</span>
        <strong>{actual?.toLocaleString()}</strong>
      </div>
      <div className="cf-tooltip-row">
        <span className="cf-dot" style={{ background: COLORS.predicted }} />
        <span>Predicted</span>
        <strong>{predicted?.toLocaleString()}</strong>
      </div>
      {delta != null && (
        <div className="cf-tooltip-row cf-tooltip-delta">
          <span>Effect</span>
          <strong style={{ color: delta >= 0 ? "#22c55e" : "#ef4444" }}>
            {delta >= 0 ? "+" : ""}
            {delta.toLocaleString(undefined, { maximumFractionDigits: 1 })}
          </strong>
        </div>
      )}
    </div>
  );
}

/**
 * Actual vs predicted counterfactual chart with a shaded confidence band.
 *
 * Recharts has no native "band between two series" mark, so the band is faked:
 * paint an Area up to the UPPER bound, then paint a second Area up to the LOWER
 * bound using mixBlendMode "destination-out". The lower Area acts as an eraser,
 * punching a hole in everything below the lower bound and leaving only the strip
 * between lower and upper filled. The hole reveals the card background behind the
 * chart, so the band adapts to light and dark themes for free.
 */
export function CounterfactualChart({
  data,
  interventionIndex,
  title,
}: CounterfactualChartProps) {
  const interventionLabel = data[interventionIndex]?.date;

  return (
    <div className="cf-chart">
      {title && <h3 className="cf-chart-title">{title}</h3>}
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={data}
          margin={{ top: 12, right: 24, left: 8, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} strokeOpacity={0.25} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: COLORS.axis }}
            stroke={COLORS.axis}
            strokeOpacity={0.4}
            interval="preserveStartEnd"
            minTickGap={40}
          />
          <YAxis
            tick={{ fontSize: 11, fill: COLORS.axis }}
            stroke={COLORS.axis}
            strokeOpacity={0.4}
            width={48}
          />
          <Tooltip content={<CounterfactualTooltip />} />

          {/* 1) Fill everything up to the UPPER bound. */}
          <Area
            dataKey="upper"
            stroke="none"
            fill={COLORS.predicted}
            fillOpacity={0.16}
            isAnimationActive={false}
            name="95% interval"
          />
          {/* 2) Erase everything up to the LOWER bound. The fill colour is
                 irrelevant for destination-out; only its alpha matters. What is
                 left is the strip between lower and upper. */}
          <Area
            dataKey="lower"
            stroke="none"
            fill="#ffffff"
            fillOpacity={1}
            isAnimationActive={false}
            legendType="none"
            style={{ mixBlendMode: "destination-out" as any }}
          />

          {/* Faint boundary lines for the band edges. */}
          <Line
            dataKey="lower"
            stroke={COLORS.predicted}
            strokeOpacity={0.35}
            strokeWidth={1}
            strokeDasharray="3 3"
            dot={false}
            isAnimationActive={false}
            legendType="none"
          />
          <Line
            dataKey="upper"
            stroke={COLORS.predicted}
            strokeOpacity={0.35}
            strokeWidth={1}
            strokeDasharray="3 3"
            dot={false}
            isAnimationActive={false}
            legendType="none"
          />

          {/* Dashed predicted counterfactual line. */}
          <Line
            dataKey="predicted"
            stroke={COLORS.predicted}
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={false}
            isAnimationActive={false}
            name="Predicted (counterfactual)"
          />

          {/* Solid actual line. */}
          <Line
            dataKey="value"
            stroke={COLORS.actual}
            strokeWidth={2.5}
            dot={false}
            isAnimationActive={false}
            name="Actual"
          />

          {/* Intervention marker. */}
          {interventionLabel != null && (
            <ReferenceLine
              x={interventionLabel}
              stroke={COLORS.intervention}
              strokeWidth={2}
              strokeDasharray="4 2"
              label={{
                value: "Intervention",
                position: "top",
                fill: COLORS.intervention,
                fontSize: 12,
                fontWeight: 600,
              }}
            />
          )}

          <Legend
            verticalAlign="bottom"
            height={32}
            iconSize={10}
            wrapperStyle={{ fontSize: 12 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
