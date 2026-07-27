import type { CSSProperties } from "react";

/**
 * A single map endpoint: a geographic coordinate plus a display label.
 */
export interface RouteEndpoint {
  /** Latitude in decimal degrees (-90 .. 90). */
  lat: number;
  /** Longitude in decimal degrees (-180 .. 180). */
  lon: number;
  /** Short text shown next to the node (e.g. "Origin", "LDN"). */
  label: string;
  /** Optional secondary caption drawn under the label. */
  sublabel?: string;
}

export interface GreatCircleRouteMapProps {
  origin: RouteEndpoint;
  destination: RouteEndpoint;
  /**
   * Optional equirectangular basemap image URL. If omitted, the component
   * renders an ocean-coloured background with a lat/lon graticule so it still
   * looks complete. Drop any public-domain equirectangular world map at
   * `public/world-equirectangular.jpg` and pass its URL to enable the
   * photographic basemap.
   */
  basemapUrl?: string;
  /** SVG viewBox width. Defaults to 800. */
  width?: number;
  /** SVG viewBox height. Defaults to 400. */
  height?: number;
  /** Degrees of padding added around the two endpoints. Defaults to 10. */
  padding?: number;
  className?: string;
  style?: CSSProperties;
}

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

/** Haversine great-circle distance in kilometres. */
function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const R = 6371;
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Choose a "nice" graticule step (in degrees) for a given span. */
function graticuleStep(range: number) {
  if (range > 120) return 30;
  if (range > 60) return 20;
  if (range > 30) return 10;
  if (range > 12) return 5;
  return 2;
}

/**
 * Great-circle flight-route map, hand-drawn in SVG.
 *
 * No d3-geo, no react-simple-maps: the equirectangular projection, the
 * quadratic-Bezier route curvature, the plane bearing (atan2) and the
 * blur/gradient/mask compositing are all built from scratch here.
 */
export function GreatCircleRouteMap({
  origin,
  destination,
  basemapUrl,
  width = 800,
  height = 400,
  padding = 10,
  className,
  style,
}: GreatCircleRouteMapProps) {
  // --- Bounding box around the two endpoints (clamped to the world) ---------
  const minLon = clamp(Math.min(origin.lon, destination.lon) - padding, -180, 180);
  const maxLon = clamp(Math.max(origin.lon, destination.lon) + padding, -180, 180);
  const minLat = clamp(Math.min(origin.lat, destination.lat) - padding, -85, 85);
  const maxLat = clamp(Math.max(origin.lat, destination.lat) + padding, -85, 85);

  const lonRange = maxLon - minLon || 1;
  const latRange = maxLat - minLat || 1;

  // --- Equirectangular projection -------------------------------------------
  // The world in normalised 0..1 space is x = (lon + 180) / 360,
  // y = (90 - lat) / 180. We work out which slice of that unit world our
  // bounding box occupies, then scale a full-world image so the slice fills
  // the whole SVG. The same linear mapping projects any lat/lon to SVG pixels.
  const mapLeft = (minLon + 180) / 360;
  const mapRight = (maxLon + 180) / 360;
  const mapTop = (90 - maxLat) / 180;
  const mapBottom = (90 - minLat) / 180;

  const fullWorldWidth = width / (mapRight - mapLeft);
  const fullWorldHeight = height / (mapBottom - mapTop);
  const mapX = -(mapLeft * fullWorldWidth);
  const mapY = -(mapTop * fullWorldHeight);

  const projectLon = (lon: number) => ((lon - minLon) / lonRange) * width;
  const projectLat = (lat: number) => height - ((lat - minLat) / latRange) * height;

  const x1 = projectLon(origin.lon);
  const y1 = projectLat(origin.lat);
  const x2 = projectLon(destination.lon);
  const y2 = projectLat(destination.lat);

  // --- Great-circle curvature via a quadratic Bezier control point ----------
  // The control point sits perpendicular to the straight midpoint, so the
  // 2D curve bulges the way a great circle appears on an equirectangular map.
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const chord = Math.sqrt(dx * dx + dy * dy) || 1;

  const curvature = Math.min(chord * 0.2, 80);
  const controlX = midX - (dy / chord) * curvature;
  const controlY = midY + (dx / chord) * curvature;

  const pathD = `M ${x1} ${y1} Q ${controlX} ${controlY} ${x2} ${y2}`;

  // --- Plane bearing: the tangent angle of the chord, in degrees ------------
  const bearing = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;

  const distanceKm = Math.round(
    haversineKm(origin.lat, origin.lon, destination.lat, destination.lon),
  );

  // --- Graticule (lat/lon grid) for the no-basemap background ---------------
  const lonStep = graticuleStep(lonRange);
  const latStep = graticuleStep(latRange);
  const lonLines: number[] = [];
  for (let lon = Math.ceil(minLon / lonStep) * lonStep; lon <= maxLon; lon += lonStep) {
    lonLines.push(lon);
  }
  const latLines: number[] = [];
  for (let lat = Math.ceil(minLat / latStep) * latStep; lat <= maxLat; lat += latStep) {
    latLines.push(lat);
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      style={{ width: "100%", height: "auto", display: "block", ...style }}
      role="img"
      aria-label={`Flight route from ${origin.label} to ${destination.label}`}
    >
      <defs>
        {/* Route stroke gradient */}
        <linearGradient id="gcrm-route" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0.9" />
        </linearGradient>

        {/* Soft glow for the route and nodes */}
        <filter id="gcrm-glow">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* Ocean background gradient (used when no basemap image is supplied) */}
        <radialGradient id="gcrm-ocean" cx="50%" cy="45%" r="75%">
          <stop offset="0%" stopColor="#12263f" />
          <stop offset="100%" stopColor="#0a0f1e" />
        </radialGradient>

        {/* Edge-fade gradients, uniform on all four sides */}
        <linearGradient id="gcrm-fadeLeft" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="black" stopOpacity="1" />
          <stop offset="10%" stopColor="white" stopOpacity="1" />
        </linearGradient>
        <linearGradient id="gcrm-fadeRight" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="90%" stopColor="white" stopOpacity="1" />
          <stop offset="100%" stopColor="black" stopOpacity="1" />
        </linearGradient>
        <linearGradient id="gcrm-fadeTop" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="black" stopOpacity="1" />
          <stop offset="10%" stopColor="white" stopOpacity="1" />
        </linearGradient>
        <linearGradient id="gcrm-fadeBottom" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="90%" stopColor="white" stopOpacity="1" />
          <stop offset="100%" stopColor="black" stopOpacity="1" />
        </linearGradient>

        {/* Compose the four fades into a single vignette mask */}
        <mask id="gcrm-edgeMask">
          <rect width={width} height={height} fill="white" />
          <rect width={width} height={height} fill="url(#gcrm-fadeLeft)" />
          <rect width={width} height={height} fill="url(#gcrm-fadeRight)" />
          <rect width={width} height={height} fill="url(#gcrm-fadeTop)" />
          <rect width={width} height={height} fill="url(#gcrm-fadeBottom)" />
        </mask>
      </defs>

      {/* Ocean-coloured background - always present so the map looks complete
          even without a photographic basemap image. */}
      <rect width={width} height={height} fill="url(#gcrm-ocean)" />

      {/* Graticule: lat/lon grid lines, only drawn when there is no basemap. */}
      {!basemapUrl && (
        <g stroke="#22415f" strokeWidth="1" opacity="0.5" mask="url(#gcrm-edgeMask)">
          {lonLines.map((lon) => {
            const x = projectLon(lon);
            return <line key={`lon-${lon}`} x1={x} y1={0} x2={x} y2={height} />;
          })}
          {latLines.map((lat) => {
            const y = projectLat(lat);
            return <line key={`lat-${lat}`} x1={0} y1={y} x2={width} y2={y} />;
          })}
        </g>
      )}

      {/* Optional equirectangular basemap image, projected to fill the box. */}
      {basemapUrl && (
        <image
          href={basemapUrl}
          x={mapX}
          y={mapY}
          width={fullWorldWidth}
          height={fullWorldHeight}
          opacity="0.5"
          preserveAspectRatio="none"
          mask="url(#gcrm-edgeMask)"
        />
      )}

      {/* Route shadow (blurred underlay). */}
      <path
        d={pathD}
        fill="none"
        stroke="#3b82f6"
        strokeWidth="3"
        strokeOpacity="0.2"
        strokeDasharray="8 4"
        filter="url(#gcrm-glow)"
      />

      {/* Animated route line. */}
      <path
        d={pathD}
        fill="none"
        stroke="url(#gcrm-route)"
        strokeWidth="2.5"
        strokeDasharray="8 4"
        strokeLinecap="round"
      >
        <animate
          attributeName="stroke-dashoffset"
          from="12"
          to="0"
          dur="1s"
          repeatCount="indefinite"
        />
      </path>

      {/* Origin node. */}
      <g>
        <circle
          cx={x1}
          cy={y1}
          r="8"
          fill="#3b82f6"
          stroke="#1e40af"
          strokeWidth="2"
          filter="url(#gcrm-glow)"
        />
        <text
          x={x1}
          y={y1 - 18}
          textAnchor="middle"
          fontSize="13"
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fontWeight="600"
          fill="#60a5fa"
        >
          {origin.label}
        </text>
        {origin.sublabel && (
          <text x={x1} y={y1 + 26} textAnchor="middle" fontSize="10" fill="#9ca3af">
            {origin.sublabel}
          </text>
        )}
      </g>

      {/* Destination node. */}
      <g>
        <circle
          cx={x2}
          cy={y2}
          r="8"
          fill="#10b981"
          stroke="#065f46"
          strokeWidth="2"
          filter="url(#gcrm-glow)"
        />
        <text
          x={x2}
          y={y2 - 18}
          textAnchor="middle"
          fontSize="13"
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          fontWeight="600"
          fill="#34d399"
        >
          {destination.label}
        </text>
        {destination.sublabel && (
          <text x={x2} y={y2 + 26} textAnchor="middle" fontSize="10" fill="#9ca3af">
            {destination.sublabel}
          </text>
        )}
      </g>

      {/* Distance caption. */}
      <text x={12} y={height - 14} fontSize="12" fill="#64748b">
        {distanceKm.toLocaleString()} km great-circle
      </text>

      {/* Bearing compass: a plane glyph rotated to the route heading (atan2). */}
      <g transform={`translate(${width - 35}, ${height - 35})`}>
        <circle r="24" fill="rgba(59, 130, 246, 0.15)" />
        <g transform={`rotate(${bearing})`}>
          <path
            d="M -10 -2.5 L 10 0 L -10 2.5 Z"
            fill="#60a5fa"
            stroke="#1e40af"
            strokeWidth="1.5"
          />
          <circle cx="-5" cy="0" r="1.5" fill="#1e40af" />
        </g>
      </g>
    </svg>
  );
}

export default GreatCircleRouteMap;
