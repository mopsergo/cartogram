/**
 * App-Orchestrierung: Timeline, Ansichten (Flat/2.5D/Globus),
 * Kennzahlen, Interpolation, Interaktion (Plan §7).
 */
import * as THREE from "three";
import { Artifacts, VALUE } from "./data/types";
import {
  LoadedApp, VariantId, VARIANT_LABELS, fetchVariantPositions,
} from "./data/artifacts";
import { Timeline } from "./timeline/timeline";
import { FlatCartogram } from "./renderers/FlatCartogram";
import { ExtrudedCartogram } from "./renderers/ExtrudedCartogram";
import { ReferenceGlobe } from "./renderers/ReferenceGlobe";
import { FrameUpdate, PickResult, lerpPositions }
  from "./renderers/shared";
import { NO_DATA_COLOR, ValueScale, formatValue, formatYear, rampColor }
  from "./renderers/colormap";
import { Legend } from "./ui/legend";
import { DetailPanel } from "./ui/panel";

type ViewMode = "flat" | "extruded" | "globe";

interface View {
  scene: THREE.Scene;
  camera: THREE.Camera;
  updateFrame(update: FrameUpdate): void;
  applyCamera(): void;
  resize(w: number, h: number): void;
  resetCamera(): void;
  pick(x: number, y: number, w: number, h: number): PickResult | null;
}

export class App {
  private art: Artifacts;
  private run: LoadedApp["run"];
  private timeline: Timeline;
  private renderer: THREE.WebGLRenderer;
  private views: Record<ViewMode, View>;
  private mode: ViewMode = "extruded";
  private metric: number = VALUE.per_capita_energy_consumption;
  /** Transformation der Farbskala (alle Kennzahlen gemeinsam) */
  private colorTransform: "linear" | "sqrt" | "log" = "sqrt";
  private heightEnabled = true;
  private ghostVisible = true;
  private geoMode = false;
  /** 0 = Kartogramm .. 1 = unverzerrte Original-Geografie (linearer Faktor) */
  private geoBlend = 0;
  private geoBlendTarget = 0;

  // ---- Flächen-Varianten (Kartogramm-Grundlage) -------------------
  private variant: VariantId;
  private variantsAvailable: VariantId[];
  /** geladene Positions-Sätze je Variante (current-Lauf) */
  private variantPositions = new Map<VariantId, Float32Array>();
  /** Positionssatz der Variante, von der gerade weggemorpht wird */
  private morphFrom: Float32Array | null = null;
  /** 0 = Ausgangsvariante .. 1 = Zielvariante (linearer Faktor) */
  private variantBlend = 1;
  private variantBlendTarget = 1;

  // ---- Positions-Puffer (kanonisch, nV × 2) ------------------------
  private interpXY: Float32Array;
  private morphXY: Float32Array;
  private vertexXY: Float32Array;
  private hovered: number | null = null;
  private selected: number | null = null;
  private selectedTriangle: number | null = null;

  private interpValues: Float32Array;
  private entityColors: Float32Array;
  private heights: Float32Array;
  private scales: Record<number, ValueScale>;
  private heightMetric: number;
  /** Höhen-Transformation: Wurzel (kleine Werte betont, Standard),
   *  linear (proportional) oder Quadrat (Spitzenwerte differenzieren) */
  private heightTransform: "sqrt" | "linear" | "square" = "sqrt";
  private worldWidth: number;
  private lastFrameKey = "";
  private legend: Legend;
  private panel: DetailPanel;
  private tooltip: HTMLElement;

  // ---- Welt-Verlaufsdiagramm (links unten) ------------------------
  /** [Bevölkerung, Gesamtenergie, Pro Kopf] je Keyframe-Jahr */
  private wcSeries: Float32Array[] = [];
  /** Jahr je Keyframe (x-Achse) */
  private wcYears!: Float32Array;
  /** Jahres-Marker im Diagramm */
  private wcMarker!: SVGLineElement;
  /** Legenden-Elemente für die aktuellen Absolutwerte */
  private wcPop!: HTMLElement;
  private wcEnergy!: HTMLElement;
  private wcPerCap!: HTMLElement;
  /** Zuletzt geschriebenes Diagramm-Jahr (DOM-Schonung) */
  private wcLastYear = NaN;
  /** Kurven-Elemente je Diagramm (relativ / absolut) */
  private wcPolysRel: SVGPolylineElement[] = [];
  private wcPolysAbs: SVGPolylineElement[] = [];
  /** Jahres-Marker im Absolut-Diagramm */
  private wcMarkerAbs!: SVGLineElement;

  private playBtn: HTMLButtonElement;
  private yearSlider: HTMLInputElement;
  private yearDisplay: HTMLElement;

  constructor(loaded: LoadedApp, dom: HTMLElement) {
    this.art = loaded.art;
    this.run = loaded.run;
    this.variant = loaded.variant;
    this.variantsAvailable = loaded.variantsAvailable;
    this.variantPositions.set(this.variant, this.art.positions);
    const nE = this.art.manifest.dimensions.num_entities;
    const nV = this.art.manifest.dimensions.num_vertices;
    this.interpXY = new Float32Array(nV * 2);
    this.morphXY = new Float32Array(nV * 2);
    this.vertexXY = new Float32Array(nV * 2);
    this.interpValues = new Float32Array(nE * 4);
    this.entityColors = new Float32Array(nE * 3);
    this.heights = new Float32Array(nE);

    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)").matches;
    this.timeline = new Timeline(this.art.manifest.years.frames,
      !reduced, 5);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      // Erlaubt Pixel-Readback (QA) und Bildexport (Plan Phase 7)
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    dom.appendChild(this.renderer.domElement);

    this.views = {
      flat: new FlatCartogram(this.art),
      extruded: new ExtrudedCartogram(this.art, this.renderer.domElement),
      globe: new ReferenceGlobe(this.art, this.renderer.domElement),
    };
    (this.views.flat as FlatCartogram).attachControls(this.renderer.domElement);
    // Ghost-Referenz initial auf beide flächenbasierten Ansichten
    (this.views.flat as FlatCartogram)
      .setGhostVisible(this.ghostVisible);
    (this.views.extruded as ExtrudedCartogram)
      .setGhostVisible(this.ghostVisible);

    // Farbskalen: Maxima aus dem Manifest, Untergrenze = kleines
    // tatsächlich vorkommendes Datenminimum (nicht 0 – sonst ver-
    // schwendet die Rampe einen Bereich, den kein Wert je erreicht,
    // und die Hälfte der Länder klebt auf den untersten Farbstufen).
    // Standard-Transformation Wurzel: beim Pro-Kopf-Median (~5,7k
    // kWh von max ~104k) läge die lineare Skala bei ~5 % Rampe;
    // Wurzel spreizt den unteren Bereich, Linear/Log umschaltbar.
    const ranges = this.art.manifest.scales.color.value_ranges;
    const vals = this.art.values;
    const dataMin = (comp: number, fallback: number): number => {
      let m = Infinity;
      for (let i = comp; i < vals.length; i += 4) {
        const v = vals[i];
        if (Number.isFinite(v) && v > 0 && v < m) m = v;
      }
      return Number.isFinite(m) ? m : fallback;
    };
    this.scales = {
      [VALUE.per_capita_energy_consumption]: new ValueScale(
        dataMin(VALUE.per_capita_energy_consumption,
          ranges.per_capita_energy_consumption.min ?? 0),
        ranges.per_capita_energy_consumption.max ?? 1,
        this.colorTransform),
      [VALUE.energy_consumption]: new ValueScale(
        dataMin(VALUE.energy_consumption,
          ranges.energy_consumption.min ?? 0),
        ranges.energy_consumption.max ?? 1, this.colorTransform),
      [VALUE.population]: new ValueScale(
        dataMin(VALUE.population, ranges.population.min ?? 0),
        ranges.population.max ?? 1, this.colorTransform),
      [VALUE.world_share]: new ValueScale(
        dataMin(VALUE.world_share, ranges.world_share.min ?? 0),
        ranges.world_share.max ?? 1, this.colorTransform),
    };
    this.heightMetric = VALUE.per_capita_energy_consumption;

    let minX = Infinity, maxX = -Infinity;
    for (let i = 0; i < nV; i++) {
      const x = this.art.positionsOriginal[i * 2];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
    }
    this.worldWidth = maxX - minX;

    this.legend = new Legend();
    this.panel = new DetailPanel(this.art);
    this.panel.onClose = () => { this.selected = null; this.markDirty(); };

    this.tooltip = document.getElementById("tooltip")!;
    this.playBtn = document.getElementById("playBtn") as HTMLButtonElement;
    this.yearSlider = document.getElementById("yearSlider") as HTMLInputElement;
    this.yearDisplay = document.getElementById("yearDisplay")!;

    this.buildWorldChart();

    this.wireControls();
    this.setMode(this.mode);   // Optionsgruppen an den Startmodus anpassen
    this.updateLegend();
    this.updateAreaLabel();
    this.resize();
    window.addEventListener("resize", () => this.resize());

    // Erst-Frame und Rendering-Loop
    this.markDirty();
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      this.timeline.tick(dt);
      // Sanfter Übergang Kartogramm <-> Original-Geografie (600 ms)
      if (this.geoBlend !== this.geoBlendTarget) {
        const step = dt / 0.6;
        this.geoBlend = this.geoBlendTarget > this.geoBlend
          ? Math.min(this.geoBlend + step, this.geoBlendTarget)
          : Math.max(this.geoBlend - step, this.geoBlendTarget);
        this.markDirty();
      }
      // Sanfter Übergang zwischen Flächen-Varianten (600 ms)
      if (this.variantBlend !== this.variantBlendTarget) {
        const step = dt / 0.6;
        this.variantBlend = this.variantBlendTarget > this.variantBlend
          ? Math.min(this.variantBlend + step, this.variantBlendTarget)
          : Math.max(this.variantBlend - step, this.variantBlendTarget);
        this.markDirty();
      }
      this.syncUI();
      this.updateFrameIfNeeded();
      const view = this.views[this.mode];
      view.applyCamera();
      this.renderer.render(view.scene, view.camera);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------- Frames

  private markDirty(): void {
    this.lastFrameKey = "";
  }

  private updateFrameIfNeeded(): void {
    const s = this.timeline.state;
    const key = `${s.frameA}|${s.frameB}|${s.t.toFixed(5)}|${this.metric}` +
      `|${this.hovered}|${this.selected}|${this.heightEnabled}` +
      `|${this.heightMetric}|${this.heightTransform}|${this.mode}` +
      `|${this.geoBlend.toFixed(3)}|${this.variant}` +
      `|${this.variantBlend.toFixed(3)}`;
    if (key === this.lastFrameKey) return;
    this.lastFrameKey = key;
    this.updateFrame();
    // Debug-Kanal (DOM, aus jeder JS-Welt lesbar)
    document.documentElement.dataset.frameKey = key;
    // Detailpanel live nachziehen (max. ~2× pro Jahresviertel)
    if (this.selected !== null &&
        Math.abs(this.timeline.displayYear - this.lastPanelYear) >= 0.25) {
      this.lastPanelYear = this.timeline.displayYear;
      this.panel.show(this.selected, this.timeline.displayYear,
        this.interpValues,
        this.countryNameFor({
          entity: this.selected,
          triangle: this.selectedTriangle ?? -1,
        }));
    }
  }

  private lastPanelYear = -1e9;

  private updateFrame(): void {
    const art = this.art;
    const nE = art.manifest.dimensions.num_entities;
    const s = this.timeline.state;
    const fa = s.frameA, fb = s.frameB, t = s.t;

    // Positionen: Jahres-Interpolation der aktiven Flächen-Variante
    // (Plan §7.1), ggf. weich überblendet von der Ausgangs-Variante
    if (this.variantBlend >= 1) this.morphFrom = null;
    lerpPositions(art, fa, fb, t, this.interpXY);
    if (this.morphFrom !== null) {
      lerpPositions(art, fa, fb, t, this.morphXY, this.morphFrom);
      // Smoothstep-Ease auf dem linearen Blend-Faktor
      const q = this.variantBlend * this.variantBlend
        * (3 - 2 * this.variantBlend);
      const inv = 1 - q;
      const n = this.vertexXY.length;
      for (let i = 0; i < n; i++) {
        this.vertexXY[i] = this.morphXY[i] * inv + this.interpXY[i] * q;
      }
    } else {
      this.vertexXY.set(this.interpXY);
    }

    // Werte interpolieren (Plan §7.1)
    for (let i = 0; i < nE * 4; i++) {
      const a = art.values[fa * nE * 4 + i];
      const b = art.values[fb * nE * 4 + i];
      this.interpValues[i] = a * (1 - t) + b * t;
    }

    // Farben: Kennzahl-Skala, keine Daten -> Grau, Hervorhebungen
    const scale = this.scales[this.metric];
    const rgb: [number, number, number] = [0, 0, 0];
    for (let e = 0; e < nE; e++) {
      const v = this.interpValues[e * 4 + this.metric];
      if (!Number.isFinite(v)) {
        rgb[0] = NO_DATA_COLOR[0];
        rgb[1] = NO_DATA_COLOR[1];
        rgb[2] = NO_DATA_COLOR[2];
      } else {
        rampColor(scale.normalize(v), rgb);
      }
      // Hervorhebung
      if (e === this.selected) {
        rgb[0] = rgb[0] * 0.55 + 0.45;
        rgb[1] = rgb[1] * 0.55 + 0.45;
        rgb[2] = rgb[2] * 0.55 + 0.45;
      } else if (e === this.hovered) {
        rgb[0] = rgb[0] * 0.75 + 0.25;
        rgb[1] = rgb[1] * 0.75 + 0.25;
        rgb[2] = rgb[2] * 0.75 + 0.25;
      }
      this.entityColors[e * 3] = rgb[0];
      this.entityColors[e * 3 + 1] = rgb[1];
      this.entityColors[e * 3 + 2] = rgb[2];
    }

    // Höhen: empfindliche Skala – linear gegen das MAXIMUM DES JAHRES
    // (nicht das globale Maximum 1820–2020: frühe Jahre hatten sonst
    // fast keine sichtbaren Unterschiede), optional Wurzel-Transfor-
    // mation für stärkere Sichtbarkeit kleinerer Werte.
    const maxFrac = art.manifest.scales.height.max_fraction ?? 0.09;
    let yearMax = 0;
    for (let e = 0; e < nE; e++) {
      const v = this.interpValues[e * 4 + this.heightMetric];
      if (Number.isFinite(v) && v > yearMax) yearMax = v;
    }
    if (yearMax <= 0) yearMax = 1;
    for (let e = 0; e < nE; e++) {
      const v = this.interpValues[e * 4 + this.heightMetric];
      if (!this.heightEnabled || !Number.isFinite(v) || v <= 0) {
        this.heights[e] = 0;
        continue;
      }
      const x = v / yearMax;
      const t = this.heightTransform === "sqrt"
        ? Math.sqrt(x)
        : this.heightTransform === "square" ? x * x : x;
      this.heights[e] = t * maxFrac * this.worldWidth;
    }

    const update: FrameUpdate = {
      vertexXY: this.vertexXY,
      entityColors: this.entityColors,
      // Höhen: 2.5D UND Globus (Extrusion auf der Kugel); nur Flach nicht
      heights: this.mode !== "flat" ? this.heights : null,
      // Smoothstep-Ease auf dem linearen Blend-Faktor
      geoBlend: this.geoBlend * this.geoBlend * (3 - 2 * this.geoBlend),
    };
    this.views[this.mode].updateFrame(update);
    // Debug-Kanal: Stichproben der Entitätsfarben (DOM-lesbar)
    const probe = [0, 30, 72].map((e) =>
      `${e}:${this.entityColors[e * 3].toFixed(2)},` +
      `${this.entityColors[e * 3 + 1].toFixed(2)}`).join(" ");
    document.documentElement.dataset.colorProbe = probe;
  }

  // ---------------------------------------------------------- UI

  private syncUI(): void {
    const year = this.timeline.displayYear;
    this.yearDisplay.textContent = formatYear(year);
    if (!this.yearSliderDragged) {
      this.yearSlider.value = String(Math.round(year));
    }
    this.updateWorldChart(year);
    const playing = this.timeline.state.playing;
    this.playBtn.textContent = playing ? "⏸" : "▶";
  }

  private yearSliderDragged = false;

  // ------------------------------------- Welt-Verlaufsdiagramm

  /** Diagramm einmalig aufbauen: Weltsummen je Keyframe-Jahr aus
   *  values.f32 (Komponenten s. VALUE), drei normierte Kurven, Jahres-
   *  Marker + Legende. Klick ins Diagramm setzt das Jahr. */
  private buildWorldChart(): void {
    const svg = document.getElementById("wcSvg") as SVGSVGElement | null;
    this.wcPop = document.getElementById("wcPop")!;
    this.wcEnergy = document.getElementById("wcEnergy")!;
    this.wcPerCap = document.getElementById("wcPerCap")!;
    if (!svg) return;

    const art = this.art;
    const nF = art.manifest.dimensions.num_frames;
    const nE = art.manifest.dimensions.num_entities;
    const frameInfos = art.manifest.years.frames;
    const frames = frameInfos.map((fi) => fi.year);
    const H = 92;   // viewBox-Höhe (Breite 250 siehe wcDrawSeries)

    // Weltsummen je Frame (NaN = keine Daten -> 0/überspringen)
    const pop = new Float32Array(nF);
    const energy = new Float32Array(nF);
    for (let f = 0; f < nF; f++) {
      let p = 0, en = 0;
      for (let e = 0; e < nE; e++) {
        const pv = art.values[(f * nE + e) * 4 + VALUE.population];
        const ev = art.values[(f * nE + e) * 4
          + VALUE.energy_consumption];
        if (Number.isFinite(pv)) p += pv;
        if (Number.isFinite(ev)) en += ev;
      }
      pop[f] = p;
      energy[f] = en;
    }
    const perCap = new Float32Array(nF);
    for (let f = 0; f < nF; f++) {
      // Mtoe -> kWh: 1 Mtoe = 10^6 toe, 1 toe = 11 630 kWh
      // (=> 1 Mtoe = 1,163e10 kWh). Gegen die gespeicherte Pro-Kopf-
      // Komponente validiert (USA 2020: exakt 93 427 kWh).
      perCap[f] = pop[f] > 0
        ? energy[f] * 11630 * 1e6 / pop[f] : NaN;
    }
    this.wcSeries = [pop, energy, perCap];
    this.wcYears = new Float32Array(frames);

    const y0 = frames[0], y1 = frames[frames.length - 1];
    const NS = "http://www.w3.org/2000/svg";

    // Zwei Diagramme: relativ (linear, Maximum) + absolut (log)
    const svgRel = svg;
    const svgAbs = document.getElementById("wcSvgAbs") as SVGSVGElement
      | null;
    this.wcDrawSeries(svgRel, "rel");
    if (svgAbs) this.wcDrawSeries(svgAbs, "abs");

    // Jahres-Marker in beiden Diagrammen (vertikal, über allem)
    const makeMarker = (svgEl: SVGSVGElement): SVGLineElement => {
      const marker = document.createElementNS(NS, "line");
      marker.setAttribute("x1", "0"); marker.setAttribute("x2", "0");
      marker.setAttribute("y1", "0"); marker.setAttribute("y2", String(H));
      marker.setAttribute("stroke", "#e6edf3");
      marker.setAttribute("stroke-width", "1");
      marker.setAttribute("opacity", "0.85");
      svgEl.appendChild(marker);
      return marker;
    };
    this.wcMarker = makeMarker(svgRel);
    if (svgAbs) this.wcMarkerAbs = makeMarker(svgAbs);

    // Klick/ziehen in beiden Diagrammen = Jahr scrubben
    const wireSeek = (svgEl: SVGSVGElement): void => {
      const seekFromEvent = (ev: PointerEvent) => {
        const r = svgEl.getBoundingClientRect();
        const t = Math.min(1,
          Math.max(0, (ev.clientX - r.left) / r.width));
        this.seekYear(y0 + t * (y1 - y0));
      };
      svgEl.addEventListener("pointerdown", (ev) => {
        seekFromEvent(ev);
        const mv = (e: PointerEvent) => seekFromEvent(e);
        const up = () => {
          window.removeEventListener("pointermove", mv);
          window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", mv);
        window.addEventListener("pointerup", up);
      });
    };
    wireSeek(svgRel);
    if (svgAbs) wireSeek(svgAbs);
  }

  /** Kurven (neu) zeichnen. Modus „rel": linear gegen das Maximum;
   *  Modus „abs": logarithmisch – zeigt Wachstumsphasen ehrlich und
   *  spreizt Werte über Größenordnungen (Absolute Werte stehen in
   *  der Legende). */
  private wcDrawSeries(svg: SVGSVGElement, mode: "rel" | "abs"): void {
    const polys = mode === "abs" ? this.wcPolysAbs : this.wcPolysRel;
    for (const p of polys) p.remove();
    polys.length = 0;

    const W = 250, H = 92, PAD = 3;
    const nF = this.wcYears.length;
    if (nF === 0) return;
    const frames = this.wcYears;
    const y0 = frames[0], y1 = frames[nF - 1];
    const xOf = (year: number): number => (year - y0) / (y1 - y0) * W;
    const abs = mode === "abs";
    const NS = "http://www.w3.org/2000/svg";
    const colors = ["var(--accent)", "var(--accent-warm)", "#9ece6a"];

    this.wcSeries.forEach((series, si) => {
      let lo = Infinity, hi = -Infinity;
      for (let f = 0; f < nF; f++) {
        const v = series[f];
        if (!Number.isFinite(v) || v <= 0) continue;
        if (v > hi) hi = v;
        if (v < lo) lo = v;
      }
      if (!Number.isFinite(lo) || hi <= lo) return;
      const relLo = abs ? lo : 0;
      const denom = abs
        ? Math.log10(hi / lo)
        : hi - relLo;
      if (denom <= 0) return;
      const mapT = (v: number): number => abs
        ? Math.log10(v / lo) / denom
        : (v - relLo) / denom;
      const pts: string[] = [];
      for (let f = 0; f < nF; f++) {
        const v = series[f];
        if (!Number.isFinite(v) || v <= 0) continue;
        const t = mapT(v);
        const y = H - PAD - t * (H - 2 * PAD);
        pts.push(`${xOf(frames[f]).toFixed(1)},${y.toFixed(1)}`);
      }
      if (pts.length < 2) return;
      const poly = document.createElementNS(NS, "polyline");
      poly.setAttribute("points", pts.join(" "));
      poly.setAttribute("fill", "none");
      poly.setAttribute("stroke", colors[si]);
      poly.setAttribute("stroke-width", "1.6");
      poly.setAttribute("stroke-linejoin", "round");
      svg.appendChild(poly);
      polys.push(poly);
    });
  }

  /** Marker + Legende auf das aktuelle Jahr stellen (gedrosselt). */
  private updateWorldChart(year: number): void {
    if (this.wcSeries.length === 0) return;
    if (Number.isFinite(this.wcLastYear)
        && Math.abs(year - this.wcLastYear) < 0.2) return;
    this.wcLastYear = year;

    const nF = this.wcYears.length;
    const y0 = this.wcYears[0], y1 = this.wcYears[nF - 1];
    const t = Math.min(1, Math.max(0, (year - y0) / (y1 - y0)));
    const mx = String(t * 250);
    this.wcMarker.setAttribute("x1", mx);
    this.wcMarker.setAttribute("x2", mx);
    if (this.wcMarkerAbs) {
      this.wcMarkerAbs.setAttribute("x1", mx);
      this.wcMarkerAbs.setAttribute("x2", mx);
    }

    // Reihenwerte am aktuellen Jahr interpolieren
    const at = (series: Float32Array): number => {
      const fy = t * (nF - 1);
      const i0 = Math.min(nF - 1, Math.max(0, Math.floor(fy)));
      const i1 = Math.min(nF - 1, i0 + 1);
      const q = fy - i0;
      const a = series[i0], b = series[i1];
      if (!Number.isFinite(a)) return b;
      if (!Number.isFinite(b)) return a;
      return a * (1 - q) + b * q;
    };
    const pop = at(this.wcSeries[0]);
    const energy = at(this.wcSeries[1]);
    const perCap = at(this.wcSeries[2]);
    this.wcPop.textContent = App.fmtBig(pop);
    this.wcEnergy.textContent = Number.isFinite(energy)
      ? App.fmtBig(energy) + " Mtoe" : "–";
    this.wcPerCap.textContent = Number.isFinite(perCap)
      ? Math.round(perCap).toLocaleString("de-DE") + " kWh" : "–";
  }

  /** Große Zahlen kompakt (deutsch): 8,1 Mrd · 1,2 M · 84.500 */
  private static fmtBig(v: number): string {
    if (!Number.isFinite(v)) return "–";
    if (v >= 1e9) {
      return (v / 1e9).toLocaleString("de-DE",
        { maximumFractionDigits: 2 }) + " Mrd";
    }
    if (v >= 1e6) {
      return (v / 1e6).toLocaleString("de-DE",
        { maximumFractionDigits: 1 }) + " M";
    }
    if (v >= 1e4) {
      return Math.round(v).toLocaleString("de-DE");
    }
    return v.toLocaleString("de-DE", { maximumFractionDigits: 1 });
  }

  private wireControls(): void {
    const viewBtns = document.getElementById("viewBtns")!;
    viewBtns.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = (btn as HTMLElement).dataset.mode as ViewMode;
        this.setMode(mode);
        viewBtns.querySelectorAll("button").forEach((b) =>
          b.classList.toggle("active", b === btn));
      });
    });

    const metricSelect = document.getElementById("metricSelect") as
      HTMLSelectElement;
    metricSelect.addEventListener("change", () => {
      this.metric = Number(metricSelect.value);
      this.updateLegend();
      this.markDirty();
    });

    const colorScaleSelect = document.getElementById("colorScaleSelect") as
      HTMLSelectElement;
    colorScaleSelect.value = this.colorTransform;
    colorScaleSelect.addEventListener("change", () => {
      const t = colorScaleSelect.value as "linear" | "sqrt" | "log";
      this.colorTransform = t;
      for (const k of Object.keys(this.scales)) {
        this.scales[Number(k)].transform = t;
      }
      this.updateLegend();
      this.markDirty();
    });

    const heightToggle = document.getElementById("heightToggle") as
      HTMLInputElement;
    heightToggle.addEventListener("change", () => {
      this.heightEnabled = heightToggle.checked;
      this.markDirty();
    });

    const heightSelect = document.getElementById("heightSelect") as
      HTMLSelectElement;
    heightSelect.value = String(this.heightMetric);
    heightSelect.addEventListener("change", () => {
      this.heightMetric = Number(heightSelect.value);
      this.markDirty();
    });

    // Höhen-Transformation: Wurzel = empfindlicher (kleine Werte
    // deutlicher), linear = proportional
    const heightScaleSelect =
      document.getElementById("heightScaleSelect") as HTMLSelectElement;
    heightScaleSelect.value = this.heightTransform;
    heightScaleSelect.addEventListener("change", () => {
      const v = heightScaleSelect.value;
      this.heightTransform =
        v === "linear" ? "linear" : v === "square" ? "square" : "sqrt";
      this.markDirty();
    });

    const ghostToggle = document.getElementById("ghostToggle") as
      HTMLInputElement;
    ghostToggle.addEventListener("change", () => {
      this.ghostVisible = ghostToggle.checked;
      (this.views.flat as FlatCartogram)
        .setGhostVisible(this.ghostVisible);
      (this.views.extruded as ExtrudedCartogram)
        .setGhostVisible(this.ghostVisible);
    });

    const geoToggle = document.getElementById("geoToggle") as
      HTMLInputElement;
    geoToggle.addEventListener("change", () => {
      this.setGeoMode(geoToggle.checked);
    });

    // Kartogramm-Fläche (Variante): gleiche Topologie, andere
    // Zielfläche – Positionssatz ggf. nachladen und weich morphen
    const variantSelect = document.getElementById("variantSelect") as
      HTMLSelectElement;
    document.getElementById("variantGroup")!.style.display =
      this.run === "current" ? "flex" : "none";
    for (const opt of Array.from(variantSelect.options)) {
      const v = opt.value as VariantId;
      const avail = this.variantsAvailable.includes(v);
      opt.disabled = !avail;
      opt.textContent = avail ? VARIANT_LABELS[v]
        : `${VARIANT_LABELS[v]} (noch nicht gelöst)`;
      if (avail && v === this.variant) opt.selected = true;
    }
    variantSelect.addEventListener("change", () => {
      this.setVariant(variantSelect.value as VariantId);
    });

    // Kartogramm-Lauf: anderer Mesh → kompletter Neuaufbau via
    // URL-Parameter (Jahr bleibt erhalten)
    const runSelect = document.getElementById("runSelect") as
      HTMLSelectElement;
    runSelect.value = this.run;
    runSelect.addEventListener("change", () => {
      const p = new URLSearchParams();
      p.set("run", runSelect.value);
      if (this.variant !== "population"
          && runSelect.value === "current") {
        p.set("variant", this.variant);
      }
      p.set("year", String(Math.round(this.timeline.displayYear)));
      location.href = `${location.pathname}?${p.toString()}`;
    });

    document.getElementById("resetCam")!.addEventListener("click", () => {
      this.views[this.mode].resetCamera();
    });

    this.playBtn.addEventListener("click", () => {
      this.timeline.setPlaying(!this.timeline.state.playing);
    });

    this.yearSlider.addEventListener("pointerdown", () => {
      this.yearSliderDragged = true;
    });
    this.yearSlider.addEventListener("pointerup", () => {
      this.yearSliderDragged = false;
    });
    this.yearSlider.addEventListener("input", () => {
      this.timeline.seekYear(Number(this.yearSlider.value));
      this.markDirty();
    });

    const speedSelect = document.getElementById("speedSelect") as
      HTMLSelectElement;
    speedSelect.addEventListener("change", () => {
      this.timeline.state.speed = Number(speedSelect.value);
    });

    window.addEventListener("keydown", (e) => {
      if (e.target instanceof HTMLSelectElement) return;
      if (e.code === "Space") {
        e.preventDefault();
        this.timeline.setPlaying(!this.timeline.state.playing);
      } else if (e.code === "ArrowLeft") {
        this.timeline.stepYear(-1);
        this.timeline.setPlaying(false);
        this.markDirty();
      } else if (e.code === "ArrowRight") {
        this.timeline.stepYear(1);
        this.timeline.setPlaying(false);
        this.markDirty();
      } else if (e.code === "KeyG") {
        this.setGeoMode(!this.geoMode);
        (document.getElementById("geoToggle") as HTMLInputElement).checked =
          this.geoMode;
      }
    });

    // Hover + Auswahl
    const canvas = this.renderer.domElement;
    canvas.addEventListener("pointermove", (e) => {
      const hit = this.views[this.mode].pick(
        e.clientX, e.clientY, canvas.clientWidth, canvas.clientHeight);
      const entity = hit ? hit.entity : null;
      if (entity !== this.hovered) {
        this.hovered = entity;
        this.markDirty();
      }
      this.updateTooltip(e, hit);
    });
    canvas.addEventListener("pointerleave", () => {
      this.hovered = null;
      this.tooltip.style.display = "none";
      this.markDirty();
    });
    canvas.addEventListener("click", (e) => {
      const hit = this.views[this.mode].pick(
        e.clientX, e.clientY, canvas.clientWidth, canvas.clientHeight);
      const entity = hit ? hit.entity : null;
      this.selected = entity;
      this.selectedTriangle = hit ? hit.triangle : null;
      if (entity !== null && hit) {
        this.panel.show(entity, this.timeline.displayYear,
          this.interpValues, this.countryNameFor(hit));
      } else {
        this.panel.hide();
      }
      this.markDirty();
    });
  }

  /** Anzeigename eines Treffers: bei Polygon-Teilen mit Ländername
   *  (Restliche Welt: Natural-Earth-Länder) das konkrete Land,
   *  sonst der Entitätsname. */
  private countryNameFor(hit: PickResult): string | undefined {
    const art = this.art;
    if (art.triangleRing && art.ringNames) {
      const ring = art.triangleRing[hit.triangle];
      if (ring !== undefined && ring < art.ringNames.length) {
        const name = art.ringNames[ring];
        if (name) return name;
      }
    }
    return undefined;
  }

  private updateTooltip(e: PointerEvent, hit: PickResult | null): void {
    if (hit === null) {
      this.tooltip.style.display = "none";
      return;
    }
    const meta = this.art.entities[hit.entity];
    const v = this.interpValues[hit.entity * 4 + this.metric];
    const name = this.countryNameFor(hit) ?? meta.display_name;
    this.tooltip.innerHTML =
      `<span class="name">${name}</span> · ` +
      `<span class="val">${formatValue(v, this.metric)}</span>` +
      (meta.is_other_world ? " (keine Energiedaten)" : "");
    this.tooltip.style.display = "block";
    const pad = 14;
    this.tooltip.style.left =
      Math.min(e.clientX + pad, window.innerWidth - 240) + "px";
    this.tooltip.style.top = (e.clientY + pad) + "px";
  }

  private updateLegend(): void {
    this.legend.update(this.scales[this.metric], this.metric,
      this.colorTransform);
  }

  private setMode(mode: ViewMode): void {
    this.mode = mode;
    // 2.5D-Optionen (Höhe) gelten für 2.5D und Globus – auch der
    // Globus extrudiert entlang der Kugelradien
    document.getElementById("heightGroup")!.style.display =
      mode === "flat" ? "none" : "flex";
    document.getElementById("flatGroup")!.style.display =
      mode === "globe" ? "none" : "flex";
    // Geometrie-Toggle gilt jetzt überall – auch der Globus morpht
    // zwischen Kartogramm-Kugel und Original-Kugel (Taste G)
    this.resize();
    this.markDirty();
  }

  /** Umschalten Kartogramm <-> unverzerrte Original-Geografie. */
  private setGeoMode(on: boolean): void {
    if (this.geoMode === on) return;
    this.geoMode = on;
    this.geoBlendTarget = on ? 1 : 0;
    this.markDirty();
  }

  /** Flächen-Variante wechseln (Positionssatz morphen, URL aktuell
   *  halten). Läuft nur für run=current (legacy hat nur Bevölkerung). */
  private async setVariant(variant: VariantId): Promise<void> {
    if (variant === this.variant
        || !this.variantsAvailable.includes(variant)) return;
    let next = this.variantPositions.get(variant) ?? null;
    if (next === null) {
      try {
        next = await fetchVariantPositions(variant);
        this.variantPositions.set(variant, next);
      } catch (err) {
        console.error("[app] Variante nicht ladbar:", err);
        (document.getElementById("variantSelect") as HTMLSelectElement)
          .value = this.variant;
        return;
      }
    }
    this.morphFrom = this.art.positions;
    this.art.positions = next;
    this.variant = variant;
    this.variantBlend = 0;
    this.variantBlendTarget = 1;
    this.markDirty();
    this.updateAreaLabel();
    const p = new URLSearchParams(location.search);
    p.set("variant", variant);
    history.replaceState(null, "", `${location.pathname}?${p.toString()}`);
  }

  /** Flächengrundlage in Titel + Legende anzeigen. */
  private updateAreaLabel(): void {
    const label = this.run === "legacy"
      ? "Bevölkerungsanteil (Original-Lauf)"
      : VARIANT_LABELS[this.variant];
    const el = document.getElementById("areaLabel");
    if (el) el.textContent = label;
    const cap = document.getElementById("legendArea");
    if (cap) cap.textContent = `Fläche = ${label}`;
  }

  // ---------------------------------------------------------- Resize

  /** Zeitleiste auf Jahr setzen (Startposition aus URL). */
  seekYear(year: number): void {
    this.timeline.seekYear(year);
    this.markDirty();
  }

  resize(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h);
    for (const view of Object.values(this.views)) {
      view.resize(w, h);
    }
    this.views[this.mode].applyCamera();
  }
}
