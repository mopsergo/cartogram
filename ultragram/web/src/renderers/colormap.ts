/**
 * Farbskalen und Normalisierung (Plan §8).
 *
 * Farbe: per_capita_energy_consumption (Standard), sequenzielle
 * Skala Plasma (wie im Bassogram-Prototyp), umschaltbar auf weitere
 * Farbskalen und Transformationen. Die Legende zeigt die tatsächlichen
 * Einheiten.
 */

export type Rgb = [number, number, number];

/** Wählbare Farbskalen (12 Stützstellen, aus matplotlib abgetastet;
 *  Reihenfolge niedrig -> hoch). */
export const COLORMAPS: Record<string, { label: string; stops: Rgb[] }> = {
  plasma: { label: "Plasma", stops: [
    [240, 249, 33], [252, 210, 37], [253, 174, 50], [246, 141, 69],
    [231, 111, 90], [213, 84, 110], [192, 58, 131], [166, 32, 152],
    [134, 6, 166], [99, 0, 167], [62, 4, 156], [13, 8, 135]] },
  viridis: { label: "Viridis", stops: [
    [253, 231, 37], [194, 223, 35], [134, 213, 73], [82, 197, 105],
    [42, 176, 127], [30, 155, 138], [37, 133, 142], [45, 112, 142],
    [56, 88, 140], [67, 62, 133], [72, 33, 115], [68, 1, 84]] },
  magma: { label: "Magma", stops: [
    [252, 253, 191], [254, 211, 149], [254, 169, 115], [250, 125, 94],
    [233, 84, 98], [200, 62, 115], [163, 48, 126], [126, 36, 130],
    [89, 21, 126], [51, 16, 103], [18, 13, 49], [0, 0, 4]] },
  inferno: { label: "Inferno", stops: [
    [252, 255, 164], [245, 219, 76], [252, 174, 18], [247, 132, 16],
    [230, 93, 47], [203, 65, 73], [169, 46, 94], [133, 33, 107],
    [95, 19, 110], [57, 9, 99], [20, 11, 52], [0, 0, 4]] },
  cividis: { label: "Cividis (farbfehlsichtig-sicher)", stops: [
    [254, 232, 56], [231, 209, 80], [206, 188, 99], [182, 169, 111],
    [157, 149, 118], [135, 132, 120], [114, 115, 116], [94, 99, 111],
    [72, 82, 108], [47, 66, 109], [1, 50, 113], [0, 34, 78]] },
  ylorrd: { label: "Gelb–Orange–Rot", stops: [
    [255, 255, 204], [255, 242, 172], [255, 228, 141], [254, 211, 111],
    [254, 181, 79], [253, 154, 66], [253, 118, 54], [250, 74, 41],
    [231, 35, 30], [206, 12, 34], [172, 0, 38], [128, 0, 38]] },
  ylgnbu: { label: "Gelb–Grün–Blau", stops: [
    [255, 255, 217], [242, 250, 188], [220, 241, 178], [187, 228, 181],
    [133, 207, 186], [87, 190, 193], [52, 169, 195], [29, 141, 190],
    [33, 102, 172], [36, 71, 157], [29, 46, 131], [8, 29, 88]] },
  turbo: { label: "Turbo (Regenbogen)", stops: [
    [48, 18, 59], [68, 84, 195], [68, 143, 254], [32, 199, 223],
    [42, 239, 161], [125, 255, 86], [193, 243, 52], [241, 203, 58],
    [254, 144, 41], [234, 78, 13], [190, 33, 2], [122, 4, 3]] },
  greys: { label: "Graustufen", stops: [
    [255, 255, 255], [244, 244, 244], [230, 230, 230], [212, 212, 212],
    [191, 191, 191], [164, 164, 164], [137, 137, 137], [112, 112, 112],
    [87, 87, 87], [57, 57, 57], [27, 27, 27], [0, 0, 0]] },
};

export const DEFAULT_COLORMAP = "plasma";

/** Aktive Rampe (für Legende, PNG-Export und rampColor) */
let ramp: Rgb[] = COLORMAPS[DEFAULT_COLORMAP].stops;

export function setColormap(name: string, reversed = false): void {
  const stops = (COLORMAPS[name] ?? COLORMAPS[DEFAULT_COLORMAP]).stops;
  ramp = reversed ? [...stops].reverse() : stops;
}

export function currentRamp(): Rgb[] {
  return ramp;
}

/** Keine Daten (z. B. Restliche Welt ohne Energiedatensatz):
 *  bewusst leiser, dunkler Grauton – sichtbar, aber zurück-
 *  tretend hinter den farbigen Datenländern. */
export const NO_DATA_COLOR: [number, number, number] = [0.28, 0.32, 0.38];

export function rampColor(t: number, out: [number, number, number]): void {
  const x = Math.min(Math.max(t, 0), 1) * (ramp.length - 1);
  const i = Math.min(Math.floor(x), ramp.length - 2);
  const f = x - i;
  const a = ramp[i];
  const b = ramp[i + 1];
  out[0] = (a[0] + (b[0] - a[0]) * f) / 255;
  out[1] = (a[1] + (b[1] - a[1]) * f) / 255;
  out[2] = (a[2] + (b[2] - a[2]) * f) / 255;
}

/** Transformation der Farbskala (vgl. Höhenskala). */
export type ColorTransform = "linear" | "sqrt" | "square" | "log";

/** Skala für eine Kennzahl: Wert -> [0,1] (linear, Wurzel, Quadrat
 *  oder log). Wurzel betont kleine Werte (empfindlich), Quadrat
 *  differenziert die Spitzenwerte, log spreizt über Größenordnungen,
 *  linear zeigt Verhältnisse proportional. */
export class ValueScale {
  min: number;
  max: number;
  transform: ColorTransform;
  /** Obergrenze ist gekappt (Ausreißer darüber in der Endfarbe) */
  openMax = false;

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
    else if (this.transform === "square") t = Math.max(0, t) ** 2;
    return Math.min(1, Math.max(0, t));
  }

  /** Skalenposition -> Anzeigewert (für Legenden-Callbacks). */
  denormalize(t: number): number {
    if (this.transform === "log") {
      const lo = Math.log10(Math.max(this.min, 1e-9));
      const hi = Math.log10(Math.max(this.max, this.min * 1.0001, 1e-9));
      return 10 ** (lo + t * (hi - lo));
    }
    const u = this.transform === "sqrt" ? t * t
      : this.transform === "square" ? Math.sqrt(Math.max(0, t)) : t;
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
  // Anzeige immer ganzzahlig – Zwischenjahre der Animation runden
  // sich auf das nächste Jahr (Benutzerwunsch), die Timeline selbst
  // interpoliert weiterhin weich.
  return String(Math.round(year));
}
