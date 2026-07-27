[← Showreel](..)

# 🗺️ Great-Circle Route Map

![Data visualisation](https://img.shields.io/badge/Data_visualisation-22c55e) ![React](https://img.shields.io/badge/React-149eca?logo=react&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A flight-route map drawn **from scratch in SVG** - no `d3-geo`, no `react-simple-maps`, no
mapping library at all. Give it two coordinates and it projects them onto an
equirectangular canvas, draws a curved great-circle route between them, and points a
little plane glyph along the bearing.

## The interesting part

Everything a mapping library would normally hide is done by hand here, which is the whole
point of the piece:

- **Hand-rolled equirectangular projection.** The world in normalised `0..1` space is
  `x = (lon + 180) / 360`, `y = (90 - lat) / 180`. The component computes which slice of
  that unit world the two endpoints occupy, then scales a full-world image so that slice
  exactly fills the SVG (`fullWorldWidth = width / (mapRight - mapLeft)`). The same linear
  mapping projects any `lat/lon` to a pixel.
- **Great-circle curvature without geodesic math.** A quadratic Bézier whose control point
  is offset perpendicular to the chord midpoint makes the 2D line bulge the way a great
  circle looks on an equirectangular map - cheap, and visually right for the common case.
- **Plane bearing from `atan2`.** The plane glyph is rotated to the chord heading
  (`atan2(dy, dx)`), so it always points down the route.
- **SVG compositing most React devs never touch.** Layered `<defs>`: a stroke gradient, a
  Gaussian-blur glow filter, a radial ocean gradient, and a four-sided edge-fade **mask**
  built by compositing four linear gradients into one vignette.
- **Haversine distance** for the great-circle-km caption.

## Run it

```bash
npm install
npm run dev
```

Open the printed local URL. You'll see three routes at different spans (long-haul,
trans-Atlantic, southern-hemisphere) to show the projection adapting its bounding box.

## The basemap is optional

Out of the box the component renders an ocean fill + a lat/lon **graticule**, so it looks
complete with **no image asset and nothing to download**. If you want a photographic
basemap, drop any **public-domain** equirectangular world map (for example from
[Natural Earth](https://www.naturalearthdata.com/), which is public domain) at
`public/world-equirectangular.jpg` and pass its URL:

```tsx
<GreatCircleRouteMap origin={...} destination={...} basemapUrl="/world-equirectangular.jpg" />
```

No image is bundled with this repo on purpose - bring your own so the licence is yours.

## What was stubbed for the demo

- The endpoint coordinates are neutral, self-chosen public cities used only to demonstrate
  the projection at different spans. Swap in whatever you like via the `origin` /
  `destination` props (`{ lat, lon, label, sublabel? }`).
- The photographic basemap is optional and not included (see above).

## API

```tsx
import { GreatCircleRouteMap, type RouteEndpoint } from "./GreatCircleRouteMap";

<GreatCircleRouteMap
  origin={{ lat: 51.47, lon: -0.46, label: "Origin" }}
  destination={{ lat: 1.36, lon: 103.99, label: "Destination" }}
  width={800}          // optional, default 800
  height={400}         // optional, default 400
  padding={10}         // optional, degrees of margin around the endpoints
  basemapUrl={...}     // optional, see above
/>;
```

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
