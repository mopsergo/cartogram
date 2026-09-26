/** Detailpanel: Werte je Entität + Sparkline der Zeitreihe. */
import { Artifacts, VALUE } from "../data/types";
import { formatValue } from "../renderers/colormap";

export class DetailPanel {
  private root: HTMLElement;
  private nameEl: HTMLElement;
  private metaEl: HTMLElement;
  private rowsEl: HTMLElement;
  private hintEl: HTMLElement;
  private canvas: HTMLCanvasElement;
  private art: Artifacts;

  constructor(art: Artifacts) {
    this.art = art;
    this.root = document.getElementById("detail")!;
    this.nameEl = document.getElementById("detailName")!;
    this.metaEl = document.getElementById("detailMeta")!;
    this.rowsEl = document.getElementById("detailRows")!;
    this.hintEl = document.getElementById("detailHint")!;
    this.canvas = document.getElementById("sparkline") as HTMLCanvasElement;
    document.getElementById("detailClose")!.addEventListener("click", () => {
      this.hide();
      if (this.onClose) this.onClose();
    });
  }

  onClose: (() => void) | null = null;

  show(entityIndex: number, displayYear: number,
       interpolated: Float32Array): void {
    const meta = this.art.entities[entityIndex];
    const flags = this.art.flags[entityIndex];
    this.root.classList.add("show");
    this.nameEl.textContent = meta.display_name;
    this.metaEl.textContent = meta.macroarea_label +
      (flags & 2 ? " · historisches Aggregat" : "") +
      (flags & 1 ? " · Auffangentität" : "");

    const comp = [VALUE.population, VALUE.world_share,
      VALUE.energy_consumption, VALUE.per_capita_energy_consumption];
    const labels = ["Bevölkerung", "Weltanteil", "Energie (Mtoe)",
      "Energie pro Kopf"];
    let html = "";
    for (let c = 0; c < 4; c++) {
      const v = interpolated[entityIndex * 4 + c];
      const txt = c === 1
        ? (Number.isFinite(v)
          ? `${(v * 100).toLocaleString("de-DE",
            { maximumFractionDigits: 2 })} %`
          : "keine Daten")
        : formatValue(v, comp[c]);
      html += `<div class="row"><span>${labels[c]}</span>` +
        `<span class="v">${txt}</span></div>`;
    }
    this.rowsEl.innerHTML = html;

    this.hintEl.textContent = meta.note ||
      "Zeitreihe 1820–2020: Bevölkerungsanteil (blau, links) und " +
      "Energie pro Kopf (orange, rechts).";
    this.drawSparkline(entityIndex, displayYear);
  }

  hide(): void {
    this.root.classList.remove("show");
  }

  private drawSparkline(entityIndex: number, displayYear: number): void {
    const art = this.art;
    const nF = art.manifest.dimensions.num_frames;
    const nE = art.manifest.dimensions.num_entities;
    const W = 220, H = 84;
    this.canvas.width = W * 2;
    this.canvas.height = H * 2;
    this.canvas.style.width = W + "px";
    this.canvas.style.height = H + "px";
    const ctx = this.canvas.getContext("2d")!;
    ctx.scale(2, 2);
    ctx.clearRect(0, 0, W, H);

    // Bevölkerungsanteil (blau, links)
    const share: number[] = [];
    const perCap: number[] = [];
    let maxShare = 0, maxPerCap = 0;
    for (let f = 0; f < nF; f++) {
      const s = art.values[(f * nE + entityIndex) * 4 + VALUE.world_share];
      const p = art.values[
        (f * nE + entityIndex) * 4 + VALUE.per_capita_energy_consumption];
      share.push(s);
      perCap.push(p);
      if (Number.isFinite(s)) maxShare = Math.max(maxShare, s);
      if (Number.isFinite(p)) maxPerCap = Math.max(maxPerCap, p);
    }

    const years = art.manifest.years.frames;
    const x = (f: number) => (f / (nF - 1)) * (W - 8) + 4;

    // Share
    ctx.strokeStyle = "#5aa9ff";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    let started = false;
    for (let f = 0; f < nF; f++) {
      const v = share[f];
      if (!Number.isFinite(v)) { started = false; continue; }
      const y = H - 6 - (v / (maxShare || 1)) * (H - 14);
      if (!started) { ctx.moveTo(x(f), y); started = true; }
      else ctx.lineTo(x(f), y);
    }
    ctx.stroke();

    // Per-Kapita (orange, linear – wie alle Skalen der App)
    if (maxPerCap > 0) {
      ctx.strokeStyle = "#ffb02e";
      ctx.beginPath();
      started = false;
      for (let f = 0; f < nF; f++) {
        const v = perCap[f];
        if (!Number.isFinite(v) || v <= 0) { started = false; continue; }
        const y = H - 6 - (v / maxPerCap) * (H - 14);
        if (!started) { ctx.moveTo(x(f), y); started = true; }
        else ctx.lineTo(x(f), y);
      }
      ctx.stroke();
    }

    // Jahrescursor
    let frameAtYear = 0;
    for (let f = 0; f < nF; f++) {
      if (years[f].year <= displayYear) frameAtYear = f;
    }
    ctx.strokeStyle = "rgba(230,237,243,0.35)";
    ctx.beginPath();
    ctx.moveTo(x(frameAtYear), 2);
    ctx.lineTo(x(frameAtYear), H - 2);
    ctx.stroke();
  }
}
