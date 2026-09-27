/** Laden und Dekodieren der Export-Artefakte (Plan §6).
 *
 * Zwei „Läufe" (runs) mit jeweils eigenem Mesh:
 *   - current: cartogram/v1 (Reparatur-Lauf) – mit zusätzlichen
 *     Flächen-Varianten v2 (Gesamtenergie) und v3 (Energie pro Kopf);
 *     gleiche Topologie, nur positions.f32 unterscheidet sich.
 *   - legacy:  cartogram/v0 – der Originalzustand aus dem Git-Commit
 *     („ursprüngliche Projektion", nur Bevölkerungs-Variante).
 *
 * Gewählt via URL: ?run=current|legacy&variant=population|energy|percapita
 */
import {
  Artifacts, EntityMeta, Manifest, Ring,
} from "./types";

const BASE = import.meta.env.BASE_URL ?? "/";

export type RunId = "current" | "legacy";
export type VariantId = "population" | "energy" | "percapita";

/** run -> Basisordner, Variante -> Unterordner (Export-VARIANT_DIRS) */
const RUN_DIRS: Record<RunId, string> = {
  current: "cartogram/v1",
  legacy: "cartogram/v0",
};
export const VARIANT_DIRS: Record<VariantId, string> = {
  population: "v1",
  energy: "v2",
  percapita: "v3",
};
export const VARIANT_LABELS: Record<VariantId, string> = {
  population: "Bevölkerungsanteil",
  energy: "Gesamtenergie",
  percapita: "Energie pro Kopf",
};

function parseRun(): RunId {
  const p = new URLSearchParams(location.search);
  return p.get("run") === "legacy" ? "legacy" : "current";
}

function parseVariant(): VariantId {
  const p = new URLSearchParams(location.search);
  switch (p.get("variant")) {
    case "energy": return "energy";
    case "percapita": return "percapita";
    default: return "population";
  }
}

async function fetchJSON<T>(dir: string, name: string): Promise<T> {
  const res = await fetch(`${BASE}${dir}/${name}`);
  if (!res.ok) throw new Error(`${dir}/${name}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

async function fetchBinary(dir: string, name: string): Promise<ArrayBuffer> {
  const res = await fetch(`${BASE}${dir}/${name}`);
  if (!res.ok) throw new Error(`${dir}/${name}: HTTP ${res.status}`);
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

/** Vollständigen Artefakt-Satz eines Laufes laden. */
async function loadRun(run: RunId): Promise<Artifacts> {
  const dir = RUN_DIRS[run];
  const t0 = performance.now();
  const [manifest, entitiesRaw] = await Promise.all([
    fetchJSON<Manifest>(dir, "manifest.json"),
    fetchJSON<{ entities: EntityMeta[] }>(dir, "entities.json"),
  ]);
  console.log(`[artifacts] ${run}: manifest+entities`,
    (performance.now() - t0).toFixed(0), "ms");

  const nF = manifest.dimensions.num_frames;
  const nV = manifest.dimensions.num_vertices;
  const nE = manifest.dimensions.num_entities;
  const nT = manifest.dimensions.num_triangles;

  const [
    positionsBuf, valuesBuf, labelsBuf, indicesBuf, rangesBuf,
    ringsBuf, flagsBuf, posOrigBuf, lonlatBuf,
  ] = await Promise.all([
    fetchBinary(dir, "positions.f32"),
    fetchBinary(dir, "values.f32"),
    fetchBinary(dir, "labels.f32"),
    fetchBinary(dir, "indices.u32"),
    fetchBinary(dir, "region_draw_ranges.u32"),
    fetchBinary(dir, "boundary_rings.u32"),
    fetchBinary(dir, "flags.u8"),
    fetchBinary(dir, "positions_original.f32"),
    fetchBinary(dir, "vertices_lonlat.f32"),
  ]);
  console.log(`[artifacts] ${run}: binaries`,
    (performance.now() - t0).toFixed(0), "ms");

  const positions = new Float32Array(positionsBuf);
  const values = new Float32Array(valuesBuf);
  const labels = new Float32Array(labelsBuf);
  const indices = new Uint32Array(indicesBuf);
  const drawRanges = new Uint32Array(rangesBuf);
  const flags = new Uint8Array(flagsBuf);
  const positionsOriginal = new Float32Array(posOrigBuf);
  const lonlat = new Float32Array(lonlatBuf);

  // Integrität: ALLE Größen prüfen (schützt vor gemischten Artefakten
  // aus verschiedenen Läufen – einzelne Dateien sind dimensions-
  // gebunden; ein Mix führt zu unsichtbaren Geometriefehlern).
  const expect = (ok: boolean, what: string) => {
    if (!ok) throw new Error(`${dir}: ${what}`);
  };
  expect(positions.length === nF * nV * 2, "positions.f32: Größe");
  expect(values.length === nF * nE * 4, "values.f32: Größe");
  expect(labels.length === nF * nE * 2, "labels.f32: Größe");
  expect(indices.length === nT * 3, "indices.u32: Größe");
  expect(drawRanges.length === nE * 2, "region_draw_ranges.u32: Größe");
  expect(flags.length === nE, "flags.u8: Größe");
  expect(positionsOriginal.length === nV * 2,
    "positions_original.f32: Größe");
  expect(lonlat.length === nV * 2, "vertices_lonlat.f32: Größe");
  expect(entitiesRaw.entities.length === nE, "entities.json: Anzahl");

  const rings = decodeRings(new Uint32Array(ringsBuf));
  console.log(`[artifacts] ${run}: dekodiert`,
    (performance.now() - t0).toFixed(0), "ms");

  // Dreieck -> Ring + Ländernamen (optional: nur neuere Exporte mit
  // Restliche-Welt-Ländern; legacy/v0 und ältere Läufe fallen auf
  // den Entitätsnamen zurück)
  let triangleRing: Uint32Array | undefined;
  let ringNames: (string | null)[] | undefined;
  try {
    triangleRing = new Uint32Array(
      await fetchBinary(dir, "triangle_ring.u32"));
    const rn = await fetchJSON<{ names: (string | null)[] }>(
      dir, "ring_names.json");
    ringNames = rn.names;
    expect(triangleRing.length === nT, "triangle_ring.u32: Größe");
    expect(ringNames.length >= manifest.dimensions.num_rings,
      "ring_names.json: Anzahl");
  } catch {
    console.info(`[artifacts] ${run}: keine Ländernamen pro Ring ` +
      "(älterer Export) – Tooltip zeigt Entitätsnamen");
  }

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
    triangleRing,
    ringNames,
  };
}

export interface LoadedApp {
  art: Artifacts;
  run: RunId;
  variant: VariantId;
  /** Für run=current: verfügbare Flächen-Varianten (v2/v3 erst nach
   *  solve+export vorhanden). legacy: nur population. */
  variantsAvailable: VariantId[];
}

/** App-Start: Lauf + Variante laden (URL-Parameter). */
export async function loadArtifacts(): Promise<LoadedApp> {
  const run = parseRun();
  const variant = run === "legacy" ? "population" : parseVariant();
  const art = await loadRun(run);

  let variantsAvailable: VariantId[] = ["population"];
  if (run === "current") {
    // v2/v3 sind optional: gleiche Topologie, nur positions.f32
    const extra: VariantId[] = ["energy", "percapita"];
    variantsAvailable = ["population"];
    for (const v of extra) {
      try {
        const m = await fetchJSON<Manifest>(
          `cartogram/${VARIANT_DIRS[v]}`, "manifest.json");
        if (m.dimensions.num_vertices
            === art.manifest.dimensions.num_vertices) {
          variantsAvailable.push(v);
        } else {
          console.warn(`[artifacts] Variante ${v}: anderes Mesh `
            + "(veralteter Export) – ignoriert");
        }
      } catch {
        console.info(`[artifacts] Variante ${v} noch nicht exportiert`);
      }
    }
    if (!variantsAvailable.includes(variant)) {
      console.warn(`[artifacts] Variante ${variant} nicht verfügbar `
        + "– falle auf population zurück");
    }
  }

  const active = variantsAvailable.includes(variant)
    ? variant : "population";
  if (active !== "population") {
    art.positions = new Float32Array(await fetchBinary(
      `cartogram/${VARIANT_DIRS[active]}`, "positions.f32"));
  }
  return { art, run, variant: active, variantsAvailable };
}

/** positions.f32 einer Variante nachladen (run=current). */
export async function fetchVariantPositions(
  variant: VariantId): Promise<Float32Array> {
  const dir = `cartogram/${VARIANT_DIRS[variant]}`;
  const buf = await fetchBinary(dir, "positions.f32");
  return new Float32Array(buf);
}

/** Wert einer Komponente für Frame und Entität (NaN = keine Daten). */
export function valueAt(art: Artifacts, frame: number, entity: number,
                        component: number): number {
  const nE = art.manifest.dimensions.num_entities;
  return art.values[(frame * nE + entity) * 4 + component];
}

export { VALUE } from "./types";
