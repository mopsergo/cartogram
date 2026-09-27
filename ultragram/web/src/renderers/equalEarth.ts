/**
 * Equal Earth (EPSG:8857) – exakte Inverse für den Kartogramm-Globus.
 *
 * Die Kartogramm-Positionen liegen in der Equal-Earth-Ebene (Meter,
 * WGS-84). Für den Globus wird je Vertex die inverse Projektion
 * benötigt: Ebene -> Länge/Breite -> Kugel. Equal Earth ist
 * flächentreu, dadurch bleiben die Kartogramm-Flächenverhältnisse
 * auf der Kugel erhalten.
 *
 * Formeln nach PROJ (proj/src/projections/eqearth.cpp, Ellipsen-Fall
 * über authalische Breite), Newton-Iteration für die parametrische
 * Breite mit Klemmung auf den Pol-Bereich – identisches Verhalten
 * wie pyproj EPSG:8857 (in der Pipeline gegen vertices_lonlat
 * verifiziert).
 */

// WGS-84
const A = 6378137.0;
const E = 0.08181919084262;
const E2 = E * E;

// Polynom-Koeffizienten (Šavrič, Patterson & Jenny 2018)
const A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796;

// √3/2
const M_VAL = Math.sqrt(3) / 2;

// Max. normierte Northing (Pol)
const MAX_Y = 1.3173627591574;

// Authalische Größen (einmalig berechnet)
function authalicQ(sinLat: number): number {
  const s = sinLat;
  return (1 - E2) * (s / (1 - E2 * s * s)
    - (1 / (2 * E)) * Math.log((1 - E * s) / (1 + E * s)));
}
const QP = authalicQ(1);
/** Authalischer Radius / halbe Achse */
const RQDA = Math.sqrt(0.5 * QP);
const SCALE = A * RQDA;

// β (authalisch) -> geodätische Breite (Reihenentwicklung, EPSG 1078)
const C1 = E2 / 3 + 31 * E2 * E2 / 180 + 517 * E2 * E2 * E2 / 5040;
const C2 = 23 * E2 * E2 / 360 + 251 * E2 * E2 * E2 / 3780;
const C3 = 761 * E2 * E2 * E2 / 45360;

/** Ableitung y'(ψ) des Equal-Earth-Polynoms. */
function yPrime(psi2: number, psi6: number): number {
  return A1 + 3 * A2 * psi2 + psi6 * (7 * A3 + 9 * A4 * psi2);
}

/**
 * Inverse Equal-Earth-Projektion: Kartogramm-Position (Meter) ->
 * [Länge, Breite] in Grad.
 *
 * out: [lonDeg, latDeg]. Bei nicht konvergierter Iteration
 * (Position außerhalb der Projektions-Domäne) wird der letzte
 *_stand zurückgegeben – Aufrufer klemmen.
 */
export function equalEarthInverse(x: number, y: number,
                                  out: [number, number]): void {
  const xs = x / SCALE;
  // Northing klemmen (Pol); PROJ-Parität
  const ys = Math.max(-MAX_Y, Math.min(MAX_Y, y / SCALE));

  // Newton für ψ: ψ·(A1 + A2ψ² + ψ⁶(A3 + A4ψ²)) = ys
  let psi = ys;
  for (let i = 0; i < 15; i++) {
    const p2 = psi * psi;
    const p6 = p2 * p2 * p2;
    const f = psi * (A1 + A2 * p2 + p6 * (A3 + A4 * p2)) - ys;
    const fder = yPrime(p2, p6);
    const d = f / fder;
    psi -= d;
    if (Math.abs(d) < 1e-11) break;
  }

  const p2 = psi * psi;
  const p6 = p2 * p2 * p2;
  let lon = M_VAL * xs * yPrime(p2, p6) / Math.cos(psi);
  // Antimeridian-Schutz: Rundung jenseits ±π zurück auf ±π klemmen
  if (Math.abs(lon) > Math.PI && Math.abs(lon) < Math.PI + 1e-9) {
    lon = Math.PI * Math.sign(lon);
  }
  const beta = Math.asin(Math.sin(psi) / M_VAL);
  const lat = beta + C1 * Math.sin(2 * beta) + C2 * Math.sin(4 * beta)
            + C3 * Math.sin(6 * beta);

  out[0] = lon * 180 / Math.PI;
  out[1] = lat * 180 / Math.PI;
}
