/**
 * Gemeinsame Renderer-Helfer: Interpolation (Plan §7.1), Non-Indexed-
 * Expansion der Topologie und Grenzlinien-Aufbau aus boundary_rings.
 */
import { Artifacts } from "../data/types";

export interface FrameUpdate {
  frameA: number;
  frameB: number;
  t: number;
  /** nE × 3 (sRGB 0..1) – Farbkennzahl + Hervorhebung */
  entityColors: Float32Array;
  /** nE – Extrusionshöhen (nur 2.5D) */
  heights: Float32Array | null;
}

/** Lineare Interpolation der Positionen zweier Frames -> out (nV × 2). */
export function lerpPositions(art: Artifacts, frameA: number, frameB: number,
                              t: number, out: Float32Array): void {
  const nV = art.manifest.dimensions.num_vertices;
  const a = frameA * nV * 2;
  const b = frameB * nV * 2;
  for (let i = 0; i < nV * 2; i++) {
    out[i] = art.positions[a + i] * (1 - t) + art.positions[b + i] * t;
  }
}

/** Expansion kanonischer Positionen auf das Non-Indexed-Dreiecksmesh. */
export function expandToTriangles(vertexXY: Float32Array,
                                  expandMap: Uint32Array,
                                  out: Float32Array): void {
  const n = expandMap.length;
  for (let s = 0; s < n; s++) {
    const v = expandMap[s] * 2;
    out[s * 2] = vertexXY[v];
    out[s * 2 + 1] = vertexXY[v + 1];
  }
}

/** Segmentliste aller Ringe: (entity, v0, v1) je Kante. */
export interface RingSegment {
  entity: number;
  v0: number;
  v1: number;
  isHole: boolean;
}

export function buildRingSegments(art: Artifacts): RingSegment[] {
  const segments: RingSegment[] = [];
  for (const ring of art.rings) {
    const ids = ring.vertexIds;
    for (let i = 0; i < ids.length; i++) {
      segments.push({
        entity: ring.entity,
        v0: ids[i],
        v1: ids[(i + 1) % ids.length],
        isHole: ring.isHole,
      });
    }
  }
  return segments;
}

/** true, wenn die Entität für die Farbkennzahl keine Daten hat. */
export function hasNoValue(value: number): boolean {
  return !Number.isFinite(value);
}
