/**
 * Gemeinsame Renderer-Helfer: Interpolation (Plan §7.1), Non-Indexed-
 * Expansion der Topologie und Grenzlinien-Aufbau aus boundary_rings.
 */
import { Artifacts } from "../data/types";

export interface FrameUpdate {
  /** Kanonische Vertex-Positionen (nV × 2): Jahres-Interpolation der
   *  aktiven Kartogramm-Variante, noch NICHT mit der Original-Geografie
   *  überblendet – das machen die Renderer über geoBlend. */
  vertexXY: Float32Array;
  /** nE × 3 (sRGB 0..1) – Farbkennzahl + Hervorhebung */
  entityColors: Float32Array;
  /** nE – Extrusionshöhen (nur 2.5D) */
  heights: Float32Array | null;
  /** 0 = Kartogramm, 1 = unverzerrte Original-Geografie (Flat/2.5D)
   *  bzw. Original-Kugel (Globus) */
  geoBlend?: number;
}

/** Lineare Interpolation der Positionen zweier Frames -> out (nV × 2).
 *  positions: optional andere Positionsvariante (Standard art.positions). */
export function lerpPositions(art: Artifacts, frameA: number, frameB: number,
                              t: number, out: Float32Array,
                              positions?: Float32Array): void {
  const nV = art.manifest.dimensions.num_vertices;
  const src = positions ?? art.positions;
  const a = frameA * nV * 2;
  const b = frameB * nV * 2;
  for (let i = 0; i < nV * 2; i++) {
    out[i] = src[a + i] * (1 - t) + src[b + i] * t;
  }
}

/**
 * Überblendet die interpolierten Kartogramm-Positionen in-place mit der
 * unverzerrten Original-Geografie (blend = 0 Kartogramm, 1 Original).
 */
export function blendWithOriginal(art: Artifacts, vertexXY: Float32Array,
                                 blend: number): void {
  if (blend <= 0) return;
  const n2 = art.manifest.dimensions.num_vertices * 2;
  const orig = art.positionsOriginal;
  if (blend >= 1) {
    vertexXY.set(orig.subarray(0, n2));
    return;
  }
  const inv = 1 - blend;
  for (let i = 0; i < n2; i++) {
    vertexXY[i] = vertexXY[i] * inv + orig[i] * blend;
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

/** Treffer eines Picks: Entität + Original-Dreieck (Ländername je Ring). */
export interface PickResult {
  entity: number;
  triangle: number;
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
