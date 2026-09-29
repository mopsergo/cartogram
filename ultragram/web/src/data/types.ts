/** Typen für die Export-Artefakte (Plan §6 – Exportvertrag). */

export interface FrameInfo {
  index: number;
  year: number;
  intermediate: boolean;
}

export interface EntityMeta {
  index: number;
  id: string;
  display_name: string;
  macroarea: string;
  macroarea_label: string;
  is_other_world: boolean;
  historical_aggregate: boolean;
  geometry_members: string[];
  note: string;
}

export interface Manifest {
  format: string;
  artifact_version: string;
  /** Zielkennzahl der Kartogramm-Fläche (data.target_metric) */
  target_metric?: string;
  /** Längengrad-Offset der Naht-Rotation (0 = klassischer
   *  Antimeridian-Schnitt). Der Globus addiert ihn zurück und zeigt
   *  die wahre Erde; 11.5 bei Naht −168.5°. */
  lon_offset_deg?: number;
  data_version: string;
  years: { data_range: [number, number]; frames: FrameInfo[] };
  dimensions: {
    num_frames: number;
    num_entities: number;
    num_vertices: number;
    num_triangles: number;
    num_rings: number;
  };
  crs: { name: string; epsg: number; units: string };
  units: Record<string, string>;
  scales: {
    area?: { metric: string; label?: string; note?: string };
    color: {
      metric: string;
      transform: string;
      ramp: string;
      value_ranges: Record<string, { min: number | null; max: number | null }>;
    };
    height: { metric: string; max_fraction: number };
  };
  solver: { chain: string[]; per_frame: unknown[] };
}

/** Werte-Komponenten in values.f32 (Reihenfolge fest im Vertrag). */
export const VALUE = {
  population: 0,
  world_share: 1,
  energy_consumption: 2,
  per_capita_energy_consumption: 3,
} as const;
export const NUM_VALUE_COMPONENTS = 4;

export interface Ring {
  entity: number;
  isHole: boolean;
  vertexIds: Uint32Array;
}

export interface Artifacts {
  manifest: Manifest;
  entities: EntityMeta[];
  /** frames × numVertices × 2 (Equal-Earth-Meter) */
  positions: Float32Array;
  /** frames × numEntities × 4 */
  values: Float32Array;
  /** frames × numEntities × 2 (Label-Anker) */
  labels: Float32Array;
  /** numTriangles × 3 */
  indices: Uint32Array;
  /** numEntities × 2 (start, count) Dreiecke */
  drawRanges: Uint32Array;
  rings: Ring[];
  flags: Uint8Array;
  /** numVertices × 2 – unverzerrte Equal-Earth-Basis */
  positionsOriginal: Float32Array;
  /** numVertices × 2 – unverzerrte Längen-/Breitengrade */
  lonlat: Float32Array;
  /** Dreieck -> Entität (aus drawRanges abgeleitet) */
  triangleEntity: Uint16Array;
  /** Expansion Karte 3T -> kanonische Vertex-IDs (Non-Indexed-Mesh) */
  expandMap: Uint32Array;
  /** Exterior-Ring-Index je Dreieck (optional, neuere Exporte) */
  triangleRing?: Uint32Array;
  /** Ländername je Ring (optional, null = Entitätsname) */
  ringNames?: (string | null)[];
}

export const FLAG_OTHER_WORLD = 1 << 0;
export const FLAG_HISTORICAL = 1 << 1;
