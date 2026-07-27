import { GreatCircleRouteMap, type RouteEndpoint } from "./GreatCircleRouteMap";

// Neutral, self-chosen public-city coordinates. Nothing proprietary here -
// just well-known places used to demonstrate the projection at different
// spans (short haul, long haul, trans-oceanic).
type Route = { origin: RouteEndpoint; destination: RouteEndpoint; note: string };

const ROUTES: Route[] = [
  {
    note: "Long haul, west-to-east",
    origin: { lat: 51.4706, lon: -0.4619, label: "Origin", sublabel: "London area" },
    destination: { lat: 1.3644, lon: 103.9915, label: "Destination", sublabel: "Singapore area" },
  },
  {
    note: "Trans-Atlantic",
    origin: { lat: 40.6413, lon: -73.7781, label: "West", sublabel: "New York area" },
    destination: { lat: 48.8566, lon: 2.3522, label: "East", sublabel: "Paris area" },
  },
  {
    note: "Southern hemisphere hop",
    origin: { lat: -33.9399, lon: 151.1753, label: "A", sublabel: "Sydney area" },
    destination: { lat: -36.8485, lon: 174.7633, label: "B", sublabel: "Auckland area" },
  },
];

export default function App() {
  return (
    <main className="page">
      <header className="masthead">
        <h1>Great-Circle Route Map</h1>
        <p>
          Flight routes drawn from scratch in SVG - a hand-rolled equirectangular
          projection, quadratic-Bezier curvature, and a plane bearing from{" "}
          <code>atan2</code>. No <code>d3-geo</code>, no map libraries.
        </p>
      </header>

      <div className="grid">
        {ROUTES.map((route) => (
          <figure className="card" key={route.note}>
            <GreatCircleRouteMap
              origin={route.origin}
              destination={route.destination}
              // Drop a public-domain equirectangular world map at
              // public/world-equirectangular.jpg and pass its URL here to get
              // the photographic basemap:
              // basemapUrl="/world-equirectangular.jpg"
            />
            <figcaption>{route.note}</figcaption>
          </figure>
        ))}
      </div>

      <footer className="footnote">
        The basemap is optional. Without an image the component still renders the
        ocean fill, graticule, animated route, nodes and bearing compass.
      </footer>
    </main>
  );
}
