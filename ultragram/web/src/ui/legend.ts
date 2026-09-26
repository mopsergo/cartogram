/** Legende: Farbskala mit Beschriftung in echten Einheiten (Plan §8). */
import { ValueScale, formatValue } from "../renderers/colormap";
import { PLASMA_R } from "../renderers/colormap";

export class Legend {
  private bar: HTMLCanvasElement;
  private minEl: HTMLElement;
  private maxEl: HTMLElement;
  private captionEl: HTMLElement;

  constructor() {
    this.bar = document.getElementById("legendBar") as HTMLCanvasElement;
    this.minEl = document.getElementById("legendMin")!;
    this.maxEl = document.getElementById("legendMax")!;
    this.captionEl = document.getElementById("legendCaption")!;
    this.drawRamp();
  }

  private drawRamp(): void {
    const w = 220, h = 14;
    this.bar.width = w;
    this.bar.height = h;
    const ctx = this.bar.getContext("2d")!;
    const grad = ctx.createLinearGradient(0, 0, w, 0);
    PLASMA_R.forEach((c, i) => {
      grad.addColorStop(i / (PLASMA_R.length - 1),
        `rgb(${c[0]},${c[1]},${c[2]})`);
    });
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
  }

  update(scale: ValueScale, component: number, transform: string): void {
    const fmt = (v: number) => {
      if (component === 1) {
        return `${(v * 100).toLocaleString("de-DE",
          { maximumFractionDigits: 1 })} %`;
      }
      return formatValue(v, component);
    };
    this.minEl.textContent = fmt(scale.min);
    this.maxEl.textContent = fmt(scale.max);
    const names: Record<number, string> = {
      0: "Bevölkerung",
      1: "Anteil an der Weltbevölkerung",
      2: "Gesamtenergieverbrauch (Mtoe)",
      3: "Energieverbrauch pro Kopf (kWh)",
    };
    this.captionEl.textContent =
      `${names[component] ?? "Wert"} · ${transform === "log"
        ? "logarithmisch" : "linear"} · Grau = keine Daten`;
  }
}
