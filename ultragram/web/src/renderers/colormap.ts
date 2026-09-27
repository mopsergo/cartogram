/**
 * Farbskalen und Normalisierung (Plan §8).
 *
 * Farbe: per_capita_energy_consumption (Standard), logarithmische
 * Normalisierung, sequenzielle Skala plasma_r (wie im Bassogram-
 * Prototyp). Die Legende zeigt die tatsächlichen Einheiten.
 */

export const PLASMA_R: [number, number, number][] = [
  [240, 249, 33], [252, 210, 37], [253, 174, 50], [246, 141, 69],
  [231, 111, 90], [213, 84, 110], [192, 58, 131], [166, 32, 152],
  [134, 6, 166], [99, 0, 167], [62, 4, 156], [13, 8, 135],
];

/** Keine Daten (z. B. Restliche Welt ohne Energiedatensatz):
 *  bewusst leiser, dunkler Grauton – sichtbar, aber zurück-
 *  tretend hinter den farbigen Datenländern. */
export const NO_DATA_COLOR: [number, number, number] = [0.28, 0.32, 0.38];

export function rampColor(t: number, out: [number, number, number]): void {
  const x = Math.min(Math.max(t, 0), 1) * (PLASMA_R.length - 1);
  const i = Math.min(Math.floor(x), PLASMA_R.length - 2);
  const f = x - i;
  const a = PLASMA_R[i];
  const b = PLASMA_R[i + 1];
  out[0] = (a[0] + (b[0] - a[0]) * f) / 255;
  out[1] = (a[1] + (b[1] - a[1]) * f) / 255;
  out[2] = (a[2] + (b[2] - a[2]) * f) / 255;
}

/** Transformation der Farbskala (vgl. Höhenskala). */
export type ColorTransform = "linear" | "sqrt" | "log";

/** Skala für eine Kennzahl: Wert -> [0,1] (linear, Wurzel oder log).
 *  Wurzel betont kleine Werte (empfindlich), log spreizt über
 *  Größenordnungen, linear zeigt Verhältnisse proportional. */
export class ValueScale {
  min: number;
  max: number;
  transform: ColorTransform;

  constructor(min: number, max: number,
             transform: ColorTransform = "linear") {
    this.min = min;
    this.max = max;
    this.transform = transform;
  }

  normalize(value: number): number {
    if (!Number.isFinite(value)) return Number.NaN;
    if (this.transform === "log") {
      const lo = Math.log10(Math.max(this.min, 1e-9));
      const hi = Math.log10(Math.max(this.max, this.min * 1.0001, 1e-9));
      if (hi <= lo) return 0;
      const v = Math.log10(Math.max(value, 1e-9));
      return Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
    }
    if (this.max <= this.min) return 0;
    let t = (value - this.min) / (this.max - this.min);
    if (this.transform === "sqrt") t = Math.sqrt(Math.max(0, t));
    return Math.min(1, Math.max(0, t));
  }

  /** Skalenposition -> Anzeigewert (für Legenden-Callbacks). */
  denormalize(t: number): number {
    if (this.transform === "log") {
      const lo = Math.log10(Math.max(this.min, 1e-9));
      const hi = Math.log10(Math.max(this.max, this.min * 1.0001, 1e-9));
      return 10 ** (lo + t * (hi - lo));
    }
    const u = this.transform === "sqrt" ? t * t : t;
    return this.min + u * (this.max - this.min);
  }
}

export function formatValue(value: number, component: number): string {
  if (!Number.isFinite(value)) return "keine Daten";
  const nf = new Intl.NumberFormat("de-DE", {
    maximumFractionDigits: value >= 100 ? 0 : 1,
  });
  switch (component) {
    case 0: // Bevölkerung (Personen)
      return `${nf.format(value)} Einw.`;
    case 1: // Weltbevölkerungsanteil
      return `${(value * 100).toLocaleString("de-DE", {
        maximumFractionDigits: 2,
      })} % der Weltbevölkerung`;
    case 2: // Gesamtenergie (Mtoe)
      return `${nf.format(value)} Mtoe`;
    case 3: // Energie pro Kopf (kWh)
      return `${nf.format(value)} kWh/Kopf`;
    default:
      return nf.format(value);
  }
}

export function formatYear(year: number): string {
  if (Number.isInteger(year)) return String(year);
  return year.toFixed(1);
}
