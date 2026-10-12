/**
 * Overlays für exportierte PNG-Frames: Jahreszahl, Farblegende und
 * Welt-Verlaufsdiagramm, direkt auf eine 2D-Canvas gezeichnet (scharf
 * in jeder Auflösung). Gestaltung wie die HUD-Elemente der App;
 * Maße in Pixeln bei 1080p, skaliert mit der Bildhöhe.
 */
import type { Rgb } from "../renderers/colormap";

/** Farblegende: Kennzahl, Skalenhinweis, Endwerte der Rampe */
export interface LegendInfo {
  title: string;
  note: string;
  min: string;
  /** Wert in der Mitte der Rampe */
  mid: string;
  max: string;
  ramp?: Rgb[];
}

/** Welt-Verlaufsdiagramm: Kurven je Keyframe-Jahr + Werte am Jahr */
export interface WorldChartInfo {
  title: string;
  years: Float32Array;
  series: Float32Array[];
  names: string[];
  /** CSS-Farben (auch var(--…)) */
  colors: string[];
  values: string[];
  year: number;
}

const PANEL = "rgba(20, 26, 36, 0.92)";
const BORDER = "#2c3646";
const TEXT = "#e6edf3";
const MUTED = "#8b98a9";

export class FrameOverlay {
  private readonly s: number;
  private readonly font: string;
  private readonly margin: number;

  constructor(private readonly ctx: CanvasRenderingContext2D,
              private readonly width: number,
              private readonly height: number) {
    this.s = height / 1080;
    this.font = getComputedStyle(document.body).fontFamily ||
      "system-ui, sans-serif";
    this.margin = 28 * this.s;
  }

  /** Jahreszahl oben links */
  drawYear(label: string): void {
    const { ctx, s } = this;
    const size = 76 * s;
    ctx.save();
    ctx.font = `700 ${size}px ${this.font}`;
    ctx.textBaseline = "top";
    ctx.fillStyle = cssColor("var(--accent-warm)");
    ctx.shadowColor = "rgba(0, 0, 0, 0.6)";
    ctx.shadowBlur = size * 0.15;
    ctx.fillText(label, this.margin, this.margin);
    ctx.restore();
  }

  /** Farblegende unten rechts: Kennzahl, Rampe, Endwerte, Skalenhinweis */
  drawLegend(info: LegendInfo): void {
    const { ctx, s } = this;
    const w = 480 * s, pad = 16 * s;
    const barH = 18 * s;
    const titleSize = 19 * s, smallSize = 15 * s;
    const h = pad + titleSize * 1.3 + 8 * s + barH + 6 * s
      + smallSize * 1.3 + 4 * s + smallSize * 1.3 + pad;
    const x = this.width - this.margin - w;
    const y = this.height - this.margin - h;
    this.panel(x, y, w, h);

    let cy = y + pad;
    ctx.save();
    ctx.textBaseline = "top";
    ctx.fillStyle = TEXT;
    ctx.font = `600 ${titleSize}px ${this.font}`;
    ctx.fillText(info.title, x + pad, cy, w - 2 * pad);
    cy += titleSize * 1.3 + 8 * s;

    const bx = x + pad, bw = w - 2 * pad;
    const grad = ctx.createLinearGradient(bx, 0, bx + bw, 0);
    const ramp = info.ramp ?? [];
    ramp.forEach((c, i) => grad.addColorStop(
      i / (ramp.length - 1), `rgb(${c[0]},${c[1]},${c[2]})`));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.roundRect(bx, cy, bw, barH, 4 * s);
    ctx.fill();
    cy += barH + 6 * s;

    ctx.font = `400 ${smallSize}px ${this.font}`;
    ctx.fillStyle = MUTED;
    ctx.fillText(info.min, bx, cy);
    ctx.textAlign = "center";
    ctx.fillText(info.mid, bx + bw / 2, cy);
    ctx.textAlign = "right";
    ctx.fillText(info.max, bx + bw, cy);
    ctx.textAlign = "left";
    cy += smallSize * 1.3 + 4 * s;
    ctx.fillText(info.note, bx, cy, bw);
    ctx.restore();
  }

  /** Welt-Verlaufsdiagramm unten links (wie das HUD der App) */
  drawWorldChart(info: WorldChartInfo): void {
    const { ctx, s } = this;
    const w = 440 * s, pad = 16 * s;
    const titleSize = 15 * s, rowSize = 17 * s;
    const plotH = 150 * s, rowH = rowSize * 1.45;
    const h = pad + titleSize * 1.4 + 6 * s + plotH + 10 * s
      + rowH * info.series.length + pad - (rowH - rowSize);
    const x = this.margin;
    const y = this.height - this.margin - h;
    this.panel(x, y, w, h);

    ctx.save();
    ctx.textBaseline = "top";
    let cy = y + pad;
    ctx.font = `600 ${titleSize}px ${this.font}`;
    ctx.fillStyle = MUTED;
    ctx.letterSpacing = `${0.08 * titleSize}px`;
    ctx.fillText(info.title.toUpperCase(), x + pad, cy, w - 2 * pad);
    ctx.letterSpacing = "0px";
    cy += titleSize * 1.4 + 6 * s;

    // Kurven relativ zum jeweiligen Maximum (wie wcDrawSeries)
    const px = x + pad, pw = w - 2 * pad, py = cy;
    const years = info.years;
    const nF = years.length;
    const y0 = years[0], y1 = years[nF - 1];
    const xOf = (yr: number) => px + (yr - y0) / (y1 - y0) * pw;
    const inset = 3 * s;
    info.series.forEach((series, si) => {
      let hi = 0;
      for (let f = 0; f < nF; f++) {
        if (Number.isFinite(series[f]) && series[f] > hi) hi = series[f];
      }
      if (hi <= 0) return;
      ctx.beginPath();
      let started = false;
      for (let f = 0; f < nF; f++) {
        const v = series[f];
        if (!Number.isFinite(v) || v <= 0) continue;
        const yy = py + plotH - inset - (v / hi) * (plotH - 2 * inset);
        if (started) ctx.lineTo(xOf(years[f]), yy);
        else { ctx.moveTo(xOf(years[f]), yy); started = true; }
      }
      ctx.strokeStyle = cssColor(info.colors[si]);
      ctx.lineWidth = 2.6 * s;
      ctx.lineJoin = "round";
      ctx.stroke();
    });

    // Jahres-Marker
    const t = Math.min(1, Math.max(0, (info.year - y0) / (y1 - y0)));
    ctx.strokeStyle = "rgba(230, 237, 243, 0.85)";
    ctx.lineWidth = 1.6 * s;
    ctx.beginPath();
    ctx.moveTo(px + t * pw, py);
    ctx.lineTo(px + t * pw, py + plotH);
    ctx.stroke();
    cy += plotH + 10 * s;

    // Legende: Farbstrich, Name, Wert am aktuellen Jahr
    ctx.font = `400 ${rowSize}px ${this.font}`;
    info.series.forEach((_, si) => {
      ctx.fillStyle = cssColor(info.colors[si]);
      ctx.fillRect(px, cy + rowSize * 0.45, 22 * s, 4 * s);
      ctx.fillStyle = MUTED;
      ctx.textAlign = "left";
      ctx.fillText(info.names[si], px + 32 * s, cy);
      ctx.fillStyle = TEXT;
      ctx.textAlign = "right";
      ctx.fillText(info.values[si], px + pw, cy);
      cy += rowH;
    });
    ctx.restore();
  }

  private panel(x: number, y: number, w: number, h: number): void {
    const { ctx, s } = this;
    ctx.save();
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 12 * s);
    ctx.fillStyle = PANEL;
    ctx.fill();
    ctx.strokeStyle = BORDER;
    ctx.lineWidth = Math.max(1, 1.5 * s);
    ctx.stroke();
    ctx.restore();
  }
}

/** CSS-Farbe auflösen (var(--x) über die :root-Variablen) */
function cssColor(c: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(c.trim());
  if (!m) return c;
  return getComputedStyle(document.documentElement)
    .getPropertyValue(m[1]).trim() || TEXT;
}
