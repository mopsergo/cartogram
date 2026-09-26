/**
 * App-Orchestrierung: Timeline, Ansichten (Flat/2.5D/Globus),
 * Kennzahlen, Interpolation, Interaktion (Plan §7).
 */
import * as THREE from "three";
import { Artifacts, VALUE } from "./data/types";
import { Timeline } from "./timeline/timeline";
import { FlatCartogram } from "./renderers/FlatCartogram";
import { ExtrudedCartogram } from "./renderers/ExtrudedCartogram";
import { ReferenceGlobe } from "./renderers/ReferenceGlobe";
import { FrameUpdate } from "./renderers/shared";
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
  pick(x: number, y: number, w: number, h: number): number | null;
}

export class App {
  private art: Artifacts;
  private timeline: Timeline;
  private renderer: THREE.WebGLRenderer;
  private views: Record<ViewMode, View>;
  private mode: ViewMode = "extruded";
  private metric: number = VALUE.per_capita_energy_consumption;
  private heightEnabled = true;
  private ghostVisible = true;
  private hovered: number | null = null;
  private selected: number | null = null;

  private interpValues: Float32Array;
  private entityColors: Float32Array;
  private heights: Float32Array;
  private scales: Record<number, ValueScale>;
  private valueMax: Record<number, number>;
  private heightMetric: number;
  private worldWidth: number;
  private lastFrameKey = "";
  private legend: Legend;
  private panel: DetailPanel;
  private tooltip: HTMLElement;

  private playBtn: HTMLButtonElement;
  private yearSlider: HTMLInputElement;
  private yearDisplay: HTMLElement;

  constructor(art: Artifacts, dom: HTMLElement) {
    this.art = art;
    const nE = art.manifest.dimensions.num_entities;
    this.interpValues = new Float32Array(nE * 4);
    this.entityColors = new Float32Array(nE * 3);
    this.heights = new Float32Array(nE);

    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)").matches;
    this.timeline = new Timeline(art.manifest.years.frames,
      !reduced, 5);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      // Erlaubt Pixel-Readback (QA) und Bildexport (Plan Phase 7)
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    dom.appendChild(this.renderer.domElement);

    this.views = {
      flat: new FlatCartogram(art),
      extruded: new ExtrudedCartogram(art, this.renderer.domElement),
      globe: new ReferenceGlobe(art, this.renderer.domElement),
    };
    (this.views.flat as FlatCartogram).attachControls(this.renderer.domElement);

    // Skalen: globale Minima/Maxima aus dem Manifest (Plan §8).
    // LINEAR (bewusst nicht logarithmisch): die krassen Unterschiede
    // zwischen Ländern und über die Zeit bleiben sichtbar.
    const ranges = art.manifest.scales.color.value_ranges;
    this.scales = {
      [VALUE.per_capita_energy_consumption]: new ValueScale(
        ranges.per_capita_energy_consumption.min ?? 0,
        ranges.per_capita_energy_consumption.max ?? 1, false),
      [VALUE.energy_consumption]: new ValueScale(
        ranges.energy_consumption.min ?? 0,
        ranges.energy_consumption.max ?? 1, false),
      [VALUE.population]: new ValueScale(
        ranges.population.min ?? 0, ranges.population.max ?? 1, false),
      [VALUE.world_share]: new ValueScale(
        ranges.world_share.min ?? 0, ranges.world_share.max ?? 1, false),
    };
    this.valueMax = {
      [VALUE.per_capita_energy_consumption]:
        ranges.per_capita_energy_consumption.max ?? 1,
      [VALUE.energy_consumption]: ranges.energy_consumption.max ?? 1,
      [VALUE.population]: ranges.population.max ?? 1,
      [VALUE.world_share]: ranges.world_share.max ?? 1,
    };
    this.heightMetric = VALUE.per_capita_energy_consumption;

    let minX = Infinity, maxX = -Infinity;
    const nV = art.manifest.dimensions.num_vertices;
    for (let i = 0; i < nV; i++) {
      const x = art.positionsOriginal[i * 2];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
    }
    this.worldWidth = maxX - minX;

    this.legend = new Legend();
    this.panel = new DetailPanel(art);
    this.panel.onClose = () => { this.selected = null; this.markDirty(); };

    this.tooltip = document.getElementById("tooltip")!;
    this.playBtn = document.getElementById("playBtn") as HTMLButtonElement;
    this.yearSlider = document.getElementById("yearSlider") as HTMLInputElement;
    this.yearDisplay = document.getElementById("yearDisplay")!;

    this.wireControls();
    this.updateLegend();
    this.resize();
    window.addEventListener("resize", () => this.resize());

    // Erst-Frame und Rendering-Loop
    this.markDirty();
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      this.timeline.tick(dt);
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
      `|${this.heightMetric}|${this.mode}`;
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
        this.interpValues);
    }
  }

  private lastPanelYear = -1e9;

  private updateFrame(): void {
    const art = this.art;
    const nE = art.manifest.dimensions.num_entities;
    const s = this.timeline.state;
    const fa = s.frameA, fb = s.frameB, t = s.t;

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

    // Höhen: LINEAR skaliert (wie die Farbskalen) auf die gewählte
    // Höhenkennzahl; Formel im Manifest dokumentiert.
    const maxFrac = art.manifest.scales.height.max_fraction ?? 0.09;
    const hMax = this.valueMax[this.heightMetric] || 1;
    for (let e = 0; e < nE; e++) {
      const v = this.interpValues[e * 4 + this.heightMetric];
      this.heights[e] = this.heightEnabled && Number.isFinite(v) && v > 0
        ? (v / hMax) * maxFrac * this.worldWidth
        : 0;
    }

    const update: FrameUpdate = {
      frameA: fa, frameB: fb, t,
      entityColors: this.entityColors,
      heights: this.mode === "extruded" ? this.heights : null,
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
    const playing = this.timeline.state.playing;
    this.playBtn.textContent = playing ? "⏸" : "▶";
  }

  private yearSliderDragged = false;

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

    const ghostToggle = document.getElementById("ghostToggle") as
      HTMLInputElement;
    ghostToggle.addEventListener("change", () => {
      this.ghostVisible = ghostToggle.checked;
      (this.views.flat as FlatCartogram)
        .setGhostVisible(this.ghostVisible);
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
      }
    });

    // Hover + Auswahl
    const canvas = this.renderer.domElement;
    canvas.addEventListener("pointermove", (e) => {
      const entity = this.views[this.mode].pick(
        e.clientX, e.clientY, canvas.clientWidth, canvas.clientHeight);
      if (entity !== this.hovered) {
        this.hovered = entity;
        this.markDirty();
      }
      this.updateTooltip(e, entity);
    });
    canvas.addEventListener("pointerleave", () => {
      this.hovered = null;
      this.tooltip.style.display = "none";
      this.markDirty();
    });
    canvas.addEventListener("click", (e) => {
      const entity = this.views[this.mode].pick(
        e.clientX, e.clientY, canvas.clientWidth, canvas.clientHeight);
      this.selected = entity;
      if (entity !== null) {
        this.panel.show(entity, this.timeline.displayYear,
          this.interpValues);
      } else {
        this.panel.hide();
      }
      this.markDirty();
    });
  }

  private updateTooltip(e: PointerEvent, entity: number | null): void {
    if (entity === null) {
      this.tooltip.style.display = "none";
      return;
    }
    const meta = this.art.entities[entity];
    const v = this.interpValues[entity * 4 + this.metric];
    this.tooltip.innerHTML =
      `<span class="name">${meta.display_name}</span> · ` +
      `<span class="val">${formatValue(v, this.metric)}</span>` +
      (meta.is_other_world ? " (keine Energiedaten)" : "");
    this.tooltip.style.display = "block";
    const pad = 14;
    this.tooltip.style.left =
      Math.min(e.clientX + pad, window.innerWidth - 240) + "px";
    this.tooltip.style.top = (e.clientY + pad) + "px";
  }

  private updateLegend(): void {
    this.legend.update(this.scales[this.metric], this.metric, "linear");
  }

  private setMode(mode: ViewMode): void {
    this.mode = mode;
    document.getElementById("heightGroup")!.style.display =
      mode === "extruded" ? "flex" : "none";
    document.getElementById("flatGroup")!.style.display =
      mode === "flat" ? "flex" : "none";
    this.resize();
    this.markDirty();
  }

  // ---------------------------------------------------------- Resize

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
