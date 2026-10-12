/** Legende: Farbskala mit Beschriftung in echten Einheiten (Plan §8). */
import { ValueScale, currentRamp, formatValue } from "../renderers/colormap";
import type { LegendInfo } from "./frameOverlay";

export class Legend {
  private bar: HTMLCanvasElement;
  private minEl: HTMLElement;
  private midEl: HTMLElement;
  private maxEl: HTMLElement;
  private captionEl: HTMLElement;
  /** Zuletzt angezeigte Beschriftung (für den PNG-Export) */
  info: LegendInfo = { title: "", note: "", min: "", mid: "", max: "" };

  constructor() {
    this.bar = document.getElementById("legendBar") as HTMLCanvasElement;
    this.minEl = document.getElementById("legendMin")!;
    this.midEl = document.getElementById("legendMid")!;
    this.maxEl = document.getElementById("legendMax")!;
    this.captionEl = document.getElementById("legendCaption")!;
    this.drawRamp();
  }

  private drawRamp(): void {
    const w = 220, h = 14;
    this.bar.width = w;
    this.bar.height = h;
    const ctx = this.bar.getContext("2d")!;
    const ramp = currentRamp();
    const grad = ctx.createLinearGradient(0, 0, w, 0);
    ramp.forEach((c, i) => {
      grad.addColorStop(i / (ramp.length - 1),
        `rgb(${c[0]},${c[1]},${c[2]})`);
    });
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
  }

  update(scale: ValueScale, component: number, transform: string): void {
    this.drawRamp();
    const fmt = (v: number) => {
      if (component === 1) {
        return `${(v * 100).toLocaleString("de-DE",
          { maximumFractionDigits: 1 })} %`;
      }
      return formatValue(v, component);
    };
    const min = fmt(scale.min);
    // Wert in der Mitte der Rampe: zeigt die Wirkung der Transformation
    const mid = fmt(scale.denormalize(0.5));
    const max = (scale.openMax ? "≥ " : "") + fmt(scale.max);
    this.minEl.textContent = min;
    this.midEl.textContent = mid;
    this.maxEl.textContent = max;
    const names: Record<number, string> = {
      0: "Bevölkerung",
      1: "Anteil an der Weltbevölkerung",
      2: "Gesamtenergieverbrauch (Mtoe)",
      3: "Energieverbrauch pro Kopf (kWh)",
    };
    const tNames: Record<string, string> = {
      linear: "lineare Skala",
      sqrt: "Wurzel-Skala",
      square: "quadratische Skala",
      log: "logarithmische Skala",
    };
    const title = names[component] ?? "Wert";
    const note = `${tNames[transform] ?? transform} · Grau = keine Daten`;
    this.captionEl.textContent = `${title} · ${note}`;
    this.info = { title, note, min, mid, max, ramp: currentRamp() };
  }
}
