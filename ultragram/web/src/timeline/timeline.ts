/**
 * Gemeinsamer Timeline-State (Plan §7.1).
 *
 *   interface TimelineState { year0; year1; t; playing; speed }
 *
 * Frames sind die vom Manifest gelieferten Keyframes (Jahre inkl.
 * eventueller Zwischen-Keyframes); t interpoliert kontinuierlich
 * zwischen frameA und frameB.
 */
import { FrameInfo } from "../data/types";

export interface TimelineState {
  frameA: number;
  frameB: number;
  t: number;
  playing: boolean;
  /** Jahre pro Sekunde */
  speed: number;
}

export class Timeline {
  readonly frames: FrameInfo[];
  state: TimelineState;
  displayYear = 1820;
  onChange: ((state: TimelineState, displayYear: number) => void) | null =
    null;

  constructor(frames: FrameInfo[], autoplay: boolean, speed = 5) {
    this.frames = frames;
    if (frames.length < 2) {
      throw new Error("Timeline benötigt mindestens zwei Frames");
    }
    this.state = {
      frameA: 0,
      frameB: Math.min(1, frames.length - 1),
      t: 0,
      playing: autoplay,
      speed,
    };
    this.displayYear = frames[0].year;
  }

  yearOf(frame: number): number {
    return this.frames[Math.min(Math.max(frame, 0),
      this.frames.length - 1)].year;
  }

  spanYears(): number {
    return Math.max(this.yearOf(this.state.frameB) -
      this.yearOf(this.state.frameA), 1e-6);
  }

  /** Zeitfortschritt in Sekunden; löst Frame-Wechsel aus. */
  tick(dtSeconds: number): void {
    if (!this.state.playing) return;
    this.state.t += (this.state.speed * dtSeconds) / this.spanYears();
    while (this.state.t >= 1) {
      if (this.state.frameB >= this.frames.length - 1) {
        this.state.t = 1;
        this.state.playing = false;
        break;
      }
      this.state.t -= 1;
      this.state.frameA = this.state.frameB;
      this.state.frameB = Math.min(this.state.frameB + 1,
        this.frames.length - 1);
    }
    this.updateDisplayYear();
  }

  private updateDisplayYear(): void {
    const y0 = this.yearOf(this.state.frameA);
    const y1 = this.yearOf(this.state.frameB);
    this.displayYear = y0 + (y1 - y0) * this.state.t;
  }

  /** Sprung zu einem (ganzzahligen) Jahr – z.B. Slider. */
  seekYear(year: number): void {
    // Frame-Paar suchen, das das Jahr einschließt
    let idx = 0;
    for (let i = 0; i < this.frames.length - 1; i++) {
      if (year >= this.frames[i].year && year <= this.frames[i + 1].year) {
        idx = i;
        break;
      }
      if (this.frames[i].year > year) {
        idx = Math.max(i - 1, 0);
        break;
      }
      idx = i;
    }
    this.state.frameA = idx;
    this.state.frameB = Math.min(idx + 1, this.frames.length - 1);
    const y0 = this.yearOf(this.state.frameA);
    const y1 = this.yearOf(this.state.frameB);
    this.state.t = y1 > y0
      ? Math.min(Math.max((year - y0) / (y1 - y0), 0), 1) : 0;
    this.updateDisplayYear();
  }

  /** Setzt t innerhalb des aktuellen Paares (Feinscrub). */
  setT(t: number): void {
    this.state.t = Math.min(Math.max(t, 0), 1);
    this.updateDisplayYear();
  }

  setPlaying(playing: boolean): void {
    this.state.playing = playing;
    if (playing && this.state.t >= 1 &&
        this.state.frameB >= this.frames.length - 1) {
      // Am Ende: Neustart
      this.state.frameA = 0;
      this.state.frameB = Math.min(1, this.frames.length - 1);
      this.state.t = 0;
    }
  }

  stepYear(delta: number): void {
    this.seekYear(Math.round(this.displayYear) + delta);
  }
}
