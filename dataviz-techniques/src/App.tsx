import { CounterfactualChart, type CounterfactualPoint } from "./CounterfactualChart";
import { DivergingScale } from "./DivergingScale";
import { ProbabilityGauge } from "./ProbabilityGauge";

// Synthetic generic series. The actual line tracks the predicted line until the
// intervention, then diverges below it while the confidence band widens.
function makeSeries(): { data: CounterfactualPoint[]; interventionIndex: number } {
  const n = 48;
  const interventionIndex = 30;
  const start = new Date("2024-01-01T00:00:00Z");
  const data: CounterfactualPoint[] = [];

  for (let i = 0; i < n; i++) {
    const d = new Date(start);
    d.setUTCDate(d.getUTCDate() + i * 7);
    const date = d.toISOString().slice(0, 10);

    const trend = 100 + i * 1.4;
    const seasonal = Math.sin(i / 3) * 8;
    const predicted = trend + seasonal;

    const drop = i >= interventionIndex ? (i - interventionIndex) * 2.4 : 0;
    const noise = Math.sin(i * 1.7) * 3;
    const value = predicted - drop + noise;

    const ciWidth = 6 + (i >= interventionIndex ? (i - interventionIndex) * 0.7 : 0);

    data.push({
      date,
      value: Math.round(value * 10) / 10,
      predicted: Math.round(predicted * 10) / 10,
      lower: Math.round((predicted - ciWidth) * 10) / 10,
      upper: Math.round((predicted + ciWidth) * 10) / 10,
    });
  }

  return { data, interventionIndex };
}

const series = makeSeries();

export default function App() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>Dataviz Techniques</h1>
        <p>
          Three small, reusable data visualisation techniques, each extracted into
          a standalone component and shown here with synthetic data.
        </p>
      </header>

      <main className="grid">
        <section className="panel">
          <h2>Masked confidence band</h2>
          <CounterfactualChart
            data={series.data}
            interventionIndex={series.interventionIndex}
          />
          <p className="caption">
            Recharts has no band-between-two-series mark. The shaded interval is
            faked: an Area is painted up to the upper bound, then a second Area up
            to the lower bound is drawn with <code>mixBlendMode: destination-out</code>,
            which erases everything below the lower bound and leaves only the strip
            between the two. The solid line is the actual series, the dashed line is
            the predicted counterfactual, and the reference line marks the
            intervention.
          </p>
        </section>

        <section className="panel">
          <h2>Dynamic-centre diverging scale</h2>
          <DivergingScale center={1.0} />
          <p className="caption">
            A diverging colour scale anchored at a centre chosen at runtime rather
            than a fixed midpoint. Below the centre it interpolates red to amber over
            <code> [0, centre]</code>; above it, amber to green over
            <code> [centre, 3 x centre]</code>. Each leg is a plain per-channel RGB
            interpolation. Null, zero and negative values fall back to neutral grey,
            so "not measured" never reads as "performed badly".
          </p>
        </section>

        <section className="panel">
          <h2>Stroke-fill probability gauge</h2>
          <div className="gauge-row">
            <div className="gauge-item">
              <ProbabilityGauge probability={0.12} />
              <span className="gauge-label">unlikely</span>
            </div>
            <div className="gauge-item">
              <ProbabilityGauge probability={0.5} />
              <span className="gauge-label">even</span>
            </div>
            <div className="gauge-item">
              <ProbabilityGauge probability={0.87} />
              <span className="gauge-label">likely</span>
            </div>
          </div>
          <p className="caption">
            A semicircular SVG gauge. The fill is a stroke trick: the arc path is
            drawn twice, once as a grey track and once with a red to amber to green
            gradient whose <code>strokeDasharray</code> is set to
            <code> probability x arcLength</code>, so only that fraction of the stroke
            is painted. The needle is a line rotated by
            <code> -90 + probability x 180</code> degrees.
          </p>
        </section>
      </main>

      <footer className="page-footer">
        Synthetic data throughout. Each component takes generic props and carries
        no dependency on any specific dataset.
      </footer>
    </div>
  );
}
