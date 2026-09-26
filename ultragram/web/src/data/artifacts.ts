/** Laden und Dekodieren der Export-Artefakte (Plan §6). */
import {
  Artifacts, EntityMeta, Manifest, Ring,
} from "./types";

const BASE = import.meta.env.BASE_URL ?? "/";
const ART = `${BASE}cartogram/v1/`;

async function fetchJSON<T>(name: string): Promise<T> {
  const res = await fetch(ART + name);
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

async function fetchBinary(name: string): Promise<ArrayBuffer> {
  const res = await fetch(ART + name);
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return res.arrayBuffer();
}

function decodeRings(data: Uint32Array): Ring[] {
  const numRings = data[0];
  const rings: Ring[] = [];
  let pos = 1;
  for (let r = 0; r < numRings; r++) {
    const entity = data[pos];
    const len = data[pos + 1];
    const isHole = data[pos + 2] !== 0;
    pos += 3;
    rings.push({
      entity,
      isHole,
      vertexIds: data.subarray(pos, pos + len),
    });
    pos += len;
  }
  return rings;
}

export async function loadArtifacts(): Promise<Artifacts> {
  const t0 = performance.now();
  const [manifest, entitiesRaw] = await Promise.all([
    fetchJSON<Manifest>("manifest.json"),
    fetchJSON<{ entities: EntityMeta[] }>("entities.json"),
  ]);
  console.log("[artifacts] manifest+entities",
    (performance.now() - t0).toFixed(0), "ms");

  const nF = manifest.dimensions.num_frames;
  const nV = manifest.dimensions.num_vertices;
  const nE = manifest.dimensions.num_entities;
  const nT = manifest.dimensions.num_triangles;

  const [
    positionsBuf, valuesBuf, labelsBuf, indicesBuf, rangesBuf,
    ringsBuf, flagsBuf, posOrigBuf, lonlatBuf,
  ] = await Promise.all([
    fetchBinary("positions.f32"),
    fetchBinary("values.f32"),
    fetchBinary("labels.f32"),
    fetchBinary("indices.u32"),
    fetchBinary("region_draw_ranges.u32"),
    fetchBinary("boundary_rings.u32"),
    fetchBinary("flags.u8"),
    fetchBinary("positions_original.f32"),
    fetchBinary("vertices_lonlat.f32"),
  ]);
  console.log("[artifacts] binaries",
    (performance.now() - t0).toFixed(0), "ms");

  const positions = new Float32Array(positionsBuf);
  const values = new Float32Array(valuesBuf);
  const labels = new Float32Array(labelsBuf);
  const indices = new Uint32Array(indicesBuf);
  const drawRanges = new Uint32Array(rangesBuf);
  const flags = new Uint8Array(flagsBuf);
  const positionsOriginal = new Float32Array(posOrigBuf);
  const lonlat = new Float32Array(lonlatBuf);

  if (positions.length !== nF * nV * 2) throw new Error("positions.f32: Größe");
  if (values.length !== nF * nE * 4) throw new Error("values.f32: Größe");
  if (indices.length !== nT * 3) throw new Error("indices.u32: Größe");

  const rings = decodeRings(new Uint32Array(ringsBuf));
  console.log("[artifacts] dekodiert",
    (performance.now() - t0).toFixed(0), "ms");

  // Dreieck -> Entität (Dreiecke sind je Entität zusammenhängend)
  const triangleEntity = new Uint16Array(nT);
  for (let e = 0; e < nE; e++) {
    const start = drawRanges[e * 2];
    const count = drawRanges[e * 2 + 1];
    for (let t = start; t < start + count; t++) triangleEntity[t] = e;
  }

  // Non-Indexed-Expansion: 3 Slots je Dreieck -> kanonische Vertex-ID
  const expandMap = new Uint32Array(nT * 3);
  for (let t = 0; t < nT; t++) {
    expandMap[t * 3 + 0] = indices[t * 3 + 0];
    expandMap[t * 3 + 1] = indices[t * 3 + 1];
    expandMap[t * 3 + 2] = indices[t * 3 + 2];
  }

  return {
    manifest,
    entities: entitiesRaw.entities,
    positions,
    values,
    labels,
    indices,
    drawRanges,
    rings,
    flags,
    positionsOriginal,
    lonlat,
    triangleEntity,
    expandMap,
  };
}

/** Wert einer Komponente für Frame und Entität (NaN = keine Daten). */
export function valueAt(art: Artifacts, frame: number, entity: number,
                       component: number): number {
  const nE = art.manifest.dimensions.num_entities;
  return art.values[(frame * nE + entity) * 4 + component];
}

export { VALUE } from "./types";
