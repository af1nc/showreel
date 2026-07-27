[← Showreel](..)

# 🎨 Dataviz Techniques

![Data visualisation](https://img.shields.io/badge/Data_visualisation-22c55e) ![React](https://img.shields.io/badge/React-149eca?logo=react&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

Three small, reusable data visualisation techniques, each extracted into a
standalone React + TypeScript component and shown side by side with synthetic
data. Built with Vite and Recharts.

The components are generic: they take plain props (a time series, a value and a
centre, a probability) and carry no dependency on any specific dataset.

## The three techniques

- `src/CounterfactualChart.tsx` - an "actual vs predicted counterfactual" line
  chart with a shaded confidence band and an intervention marker.
- `src/DivergingScale.tsx` - exports `getDivergingColor(value, center)` plus a
  demo grid of cells coloured by it.
- `src/ProbabilityGauge.tsx` - a semicircular SVG gauge driven by a single
  `probability` prop.

## The interesting part

- **The masked confidence band.** Recharts has no native mark for a band between
  two series. This fakes one by painting an Area up to the upper bound, then
  painting a second Area up to the lower bound with
  `mixBlendMode: "destination-out"`. The lower Area behaves as an eraser and
  punches out everything below the lower bound, leaving only the strip between
  the two curves filled. Because the hole reveals whatever is behind the chart,
  the band picks up the card background and adapts to light and dark themes for
  free. The fill colour of the eraser Area is irrelevant; only its alpha matters.

- **The dynamic-centre diverging scale done as RGB lerps.** Most diverging
  palettes assume a fixed midpoint. This one anchors at a centre supplied at
  runtime (a break-even point, a median, a target). Below the centre it
  interpolates red to amber over `[0, centre]`; above it, amber to green over
  `[centre, 3 x centre]`, clamped at the top. Each leg is a plain per-channel
  linear interpolation between two RGB triples. Anchoring at a runtime centre is
  what stops one large outlier from washing the whole scale to a single hue.
  Null, zero and negative values return a neutral grey so that "not measured"
  never reads as "performed badly".

- **The strokeDasharray-as-fill gauge.** The gauge is one arc path drawn twice:
  a grey track and a gradient copy. Setting the gradient copy's
  `strokeDasharray` to `probability x arcLength` paints exactly that fraction of
  the arc and leaves the rest as a gap, so the dash pattern acts as the fill
  level. The needle is a straight line rotated by `-90 + probability x 180`
  degrees.

## Run it

```bash
npm install && npm run dev
```

Then open the URL Vite prints. To type-check and produce a production build:

```bash
npm run build
```

## What was stubbed

The original components were wired to live metrics. Here they run on synthetic,
generic data generated in `src/App.tsx`: a made-up series for the counterfactual
chart, a fixed list of numbers for the diverging grid, and three hard-coded
probabilities for the gauges. All metric-specific naming has been replaced with
a generic "metric" and "value".

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
