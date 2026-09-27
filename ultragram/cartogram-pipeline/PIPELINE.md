# PIPELINE.md – Die Cartogramm-Pipeline Schritt für Schritt

Dieses Dokument beschreibt, **was** die Pipeline in jedem Schritt
berechnet, **welche Befehle** in **welcher Reihenfolge** nötig sind und
wie man die Module **direkt mit Python** starten kann.

---

## 1. Überblick

Ziel: ein animiertes Kartogramm der Welt 1820–2020, bei dem die
**Fläche** jedes Landes seinem Anteil an einer Zielgröße entspricht
(Standard: Weltbevölkerung; umschaltbar auf Gesamtenergie bzw. Energie
pro Kopf). Die Farbe kodiert den Energieverbrauch pro Kopf, die Höhe
(optional, 2.5D) eine wählbare Kennzahl.

```
data/raw/*.csv                      OWID-basierte Faktengrundlage
data/reference/ne_110m_*.geojson    Natural-Earth-Ländergeometrien
        │
        ▼
[validate/ingest]  →  data/intermediate/canonical.parquet
        │             (eine Zeile je Entität × Jahr, geprüfte Anteile)
        ▼
[mesh]             →  build-cache/mesh.npz + .stamp
        │             (feste Vertex-IDs, Ringe, Dreiecke, Equal Earth)
        ▼
[solve]            →  build-cache/frames/frame_*.npz + index_*.json
        │             (Positionen je Jahr, Qualitätsstatistik, Cache)
        ▼
[export]           →  dist/cartogram/v1|v2|v3/  (Browserartefakte)
        │             + Kopie nach ../web/public/cartogram/<vN>
        ▼
Web-App (ultragram/web)  lädt die Artefakte, rechnet NICHT selbst
```

**Wichtiges Prinzip**: Der Browser führt keine Berechnung aus – jede
Geometrie, jeder Farbwert und jede Qualitätskennzahl wird offline in
Python vorbereitet (Plan §1). Die Web-App interpoliert nur noch
zwischen fertigen Jahres-Keyframes.

---

## 2. Die Schritte im Detail

### 2.1 `validate` – Rohdaten prüfen

Liest `configs/pipeline.yaml` (`data:`), prüft die CSV-Spalten
(`Country, Macroarea, Year, Population, Energy_consumption,
World_population, World_share, Per_capita_energy_consumption`) und die
zentralen Invarianten:

- Jahre vollständig 1820–2020,
- `World_share == Population / World_population` (Toleranz
  `share_tolerance`),
- OTHER_WORLD-Anteil == 1 − Summe der erfassten Länder
  (`remainder_tolerance`),
- jeder Quellname ist im Entitätenregister (`entities.yaml`) enthalten.

### 2.2 `ingest` – kanonisches Parquet

`CSV → data/intermediate/canonical.parquet`. Pro Entität × Jahr eine
Zeile. Fehlt OTHER_WORLD in der CSV, wird es hier aus der Differenz
Weltbevölkerung − erfasste Länder **berechnet und ergänzt** (keine
Energiedaten, nur Bevölkerung). Die Entitäts-Zuordnung läuft über
`source_names` aus `entities.yaml` (z. B. `UK → GBR`).

### 2.3 `mesh` – kanonisches Mesh (einmalig)

`build_entity_geometries` + `build_mesh` + `triangulate_mesh`:

1. **Natural Earth 110m laden** (lokal bevorzugt, URL-Fallback),
   Geometrien mit `buffer(0)` reparieren.
2. **Entitäten dissolven**: eine Entität = eine (Multi-)Polygon-
   Geometrie. Historische Aggregate (UdSSR, Jugoslawien, …) bleiben
   **verschmolzen** – eine Datenentität, eine Form.
3. **OTHER_WORLD = alle unbeanspruchten Länder** (ohne Antarktis,
   konfiguriert in `exclude_features`) – **bewusst NICHT verschmolzen**:
   jedes Land bleibt eigener Polygon-Teil, damit die tatsächlich
   vorhandenen Länder im Kartogramm erkennbar bleiben. Geteilte
   Grenzen verschweißt der Mesh-Bau über die Koordinaten-Dedupe
   (`vertex_precision_m`) zu einer gemeinsamen Vertex-Kette.
4. **Projektion nach Equal Earth (EPSG:8857)** – flächentreu, damit
   „Fläche = Anteil" geometrisch exakt bleibt.
5. **Vertices global deduplizieren** (feste IDs; Nachbarn teilen
   Grenzvertices → Grenzen bleiben beim Verformen gekoppelt),
   **Ringe** (Exterior + Holes) je Polygon-Teil, **Dreiecke** per
   Ear-Clipping (`mapbox-earcut`) nur auf Ringvertices – die
   Topologie ist damit für **alle** Jahre identisch.
6. Cache: `build-cache/mesh.npz`, Gültigkeit über einen Hash aus
   **allen Konfigurationsdateien + der Natural-Earth-Datei** (.stamp).

### 2.4 `solve` – Jahres-Keyframes (der eigentliche Solver)

Für jedes Jahr 1820–2020 (optional `--years`):

1. **Zielgewichte laden** (`targets_for_year`, `data.target_metric`):
   - `world_share` → Fläche = Weltbevölkerungsanteil (Standard, v1),
   - `energy_consumption` → Fläche = Anteil am Weltenergieverbrauch (v2),
   - `per_capita_energy_consumption` → Fläche ∝ Energie pro Kopf (v3).
   Anteile werden auf 1 normiert; Entitäten **ohne Wert** der Kennzahl
   sind *passiv* (kein Ziel, Dichte 1: OTHER_WORLD, Israel < 1950).
   Water-Filling: Anteile unter `min_target_share` werden aufgestockt
   (kleinere Länder wären mit dem 110m-Mesh nicht darstellbar), der
   Rest renormiert.
2. **carto_flow-Solver** (flow-based, Gastner/Seguy/More 2018):
   Dichtefeld ρ = Zieldichte/Istfläche auf einem 1024er-Gitter,
   Poisson-Gleichung per Spiegelungs-FFT, Zeitintegration 0→1 mit
   Prädiktor-Korrektor. Pro Jahr ein **Direct Solve** vom
   unverzerrten Ausgangszustand (`warm_start: false`).
3. **Qualitätsprüfung** je Kandidat (`quality.validate_keyframe`):
   p90/max-Flächenfehler gegen die Ziele, Faltflächen-Quote
   (eingeklappte Dreiecke), Dreiecksinversion, Verschiebungsanteil.
   Schwellen in `pipeline.yaml → temporal.quality`.
4. **Reparatur** (`repair.py`, „nur reparieren, wenn es besser ist"):
   Polygone, die im Flow ungültig wurden (Selbstdurchdringung), werden
   durch starr skalierte Originalformen ersetzt – aber nur, wenn das
   Ergebnis den Flächenfehler **nachweislich verbessert** (≤ 0.25);
   sonst bleibt der Flow stehen (dokumentierte Warnung statt
   Fake-Flächen). Zwischen Jahren wird der Skalierungsfaktor im
   lokalen Fenster weitergeführt (keine Sprünge), Reparatur- und
   Skip-Zustand wandern mit dem Vorjahr (Hysterese – kein Flackern).
5. **Übergangsprüfung**: lineare Interpolation zweier Keyframes auf
   Dreiecksinversion getestet (`transition_samples`); im Fehlerfall
   wird ein zusätzlicher Zwischen-Keyframe mit gemittelten Zielen
   gelöst.
6. **Cache**: jede Frame-Datei heißt `frame_<solverhash>_<jahr>.npz`
   und enthält Positionen + Targets-Hash + Statistik. Der Index
   (`index_<solverhash>.json`) versioniert über Mesh-Hash + Solver- +
   **Zielkennzahl**-Konfiguration. Bereits gelöste Jahre werden
   übersprungen (inkrementell).

   **Metric-Verifikation beim Laden** (`export`, `debug-frames`,
   `quality`, `verify-stability`): fehlt der erwartete Index – z. B.
   nach Konfigurationskosmetik –, wird ein vorhandener Kandidat nur
   dann adoptiert, wenn die im Frame gespeicherten **Targets** gegen
   die frisch berechneten Targets der aktiven Zielkennzahl passen.
   Ein bereits vorhandener erwarteter Index wird ebenso
   stichprobenartig verifiziert. Das verhindert, dass eine Variante
   stumm mit den Frames einer anderen Kennzahl exportiert wird –
   genau solche falsch adoptierten Indizes hatten dafür gesorgt,
   dass v2 und v3 byteidentisch mit v1 waren und der
   Varianten-Wechsel in der Web-App sichtbar nichts tat.

**Laufzeit**: frühe Jahre sind teuer (extreme Kontraktionen, viele
Solver-Iterationen), späte schnell; insgesamt ~20–40 min für 201
Jahre auf einem modernen Mac.

### 2.5 `export` – Browserartefakte

Schreibt nach `dist/cartogram/<variante>/` und kopiert nach
`../web/public/cartogram/<variante>/` (Basis: `paths.web_public`):

| Datei | Inhalt |
|---|---|
| `positions.f32` | [Frames, Vertices, 2] – Jahres-Keyframes, Equal-Earth-Meter |
| `positions_original.f32` | unverzerrte Basis (Geometrie-Toggle, Taste G) |
| `vertices_lonlat.f32` | Länge/Breite je Vertex (Globus) |
| `values.f32` | [Frames, Entitäten, 4] – Bevölkerung, Anteil, Energie, Energie/Kopf (NaN = keine Daten) |
| `labels.f32` | Label-Anker (repräsentativer Innenpunkt) |
| `indices.u32`, `region_draw_ranges.u32`, `boundary_rings.u32`, `topology.bin`, `surface_vertex_to_canonical.u32`, `flags.u8` | feste Topologie |
| `entities.json`, `manifest.json` | Metadaten (inkl. `target_metric`, Prüfsummen aller Dateien) |
| `quality.parquet` | Qualitätsbericht je Frame/Entität |

Die Varianten-Ordner folgen aus der Zielkennzahl
(`config.VARIANT_DIRS`): `world_share → v1`, `energy_consumption →
v2`, `per_capita_energy_consumption → v3`. **Topologie, Werte und
Entitäten sind in allen Varianten identisch** – nur `positions.f32`
und `quality.parquet` unterscheiden sich. Der Renderer lädt v1
vollständig und zusätzlich nur die `positions.f32` der gewählten
Variante.

`web/public/cartogram/v0/` ist der **Original-Lauf aus dem Git-Commit**
(„ursprüngliche Projektion") – im Renderer über „Kartogramm-Lauf"
umschaltbar.

### 2.6 Prüf- und Debug-Werkzeuge

- `quality [--metric …]` – fasst `quality.parquet` der Variante
  zusammen (Frames mit Problemen, p90/max-Verteilung).
- `verify-stability [--metric …]` – prüft die exportierten Keyframes
  auf Sprünge: Vertex-Verschiebung Jahr zu Jahr, Flächenfehler-
  Sprünge, Kandidatenwechsel. Reparatur-Übergänge (einmalig, im
  Bericht markiert) gelten als dokumentierte Transitionen.
- `debug-frames --years 1820 1850 … --out debug_frames` – rendert
  Matplotlib-PNGs je Jahr (mit unverzerrter Ghost-Referenz).

---

## 3. Befehle in der richtigen Reihenfolge

### 3.1 Kompletter Lauf (eine Variante, alles frisch)

```bash
cd ultragram/cartogram-pipeline
export PYTHONPATH=src

python3 -m worldcarto.cli validate   # 1. Rohdaten prüfen (Sekunden)
python3 -m worldcarto.cli ingest     # 2. kanonisches Parquet (Sekunden)
python3 -m worldcarto.cli mesh        # 3. Mesh (~10–30 s, gecacht)
python3 -m worldcarto.cli solve      # 4. Keyframes (~20–40 min, gecacht)
python3 -m worldcarto.cli export     # 5. Artefakte + Web-Kopie (~1 min)

# Kurzform für 1–5 in einem Durchgang (aktuell konfigurierte Variante):
python3 -m worldcarto.cli build
```

### 3.2 Alle drei Flächen-Varianten

`pipeline.yaml → data.target_metric` legt die Variante fest; der
Schalter `--metric` überschreibt sie je Aufruf (ohne die Config zu
ändern). Das Mesh ist für alle Varianten identisch und wird nur einmal
gebaut:

```bash
cd ultragram/cartogram-pipeline
export PYTHONPATH=src

# Variante v1: Bevölkerungsanteil (Standard)
python3 -m worldcarto.cli solve
python3 -m worldcarto.cli export

# Variante v2: Gesamtenergie
python3 -m worldcarto.cli solve  --metric energy_consumption
python3 -m worldcarto.cli export --metric energy_consumption

# Variante v3: Energie pro Kopf
python3 -m worldcarto.cli solve  --metric per_capita_energy_consumption
python3 -m worldcarto.cli export --metric per_capita_energy_consumption

# Prüfbericht je Variante
python3 -m worldcarto.cli quality         --metric energy_consumption
python3 -m worldcarto.cli verify-stability --metric energy_consumption
```

### 3.3 Nach Änderungen – was muss neu laufen?

| Änderung | nötig |
|---|---|
| `pipeline.yaml` (Qualität/Flow) | `solve` neu (Cache invalidiert automatisch), danach `export` |
| `data.target_metric` | nur `solve` + `export` der betroffenen Variante (Mesh bleibt) |
| `entities.yaml` / `pipeline.yaml` (Geometrie) | `mesh --force`, dann **alle** Varianten neu lösen + exportieren |
| Natural-Earth-Datei ersetzt | wie entities.yaml (Mesh-Hash enthält die Datei) |
| nur `repair.py`/`quality.py` angefasst | `solve` neu (Frame-Cache bleibt gültig, wenn Targets gleich; sonst läuft er automatisch an), `export` |
| nur Renderer/web | nichts hier – `export` unverändert lassen, `npm run build` im Web |

Frame-Caches werden **nicht** automatisch gelöscht: Ein neuer
Solver-/Metric-Hash erzeugt neue Dateien; alte `frame_*.npz` können per
Hand gelöscht werden (`rm build-cache/frames/frame_*.npz`), wenn
Speicher fehlt.

### 3.4 Webbapp starten

```bash
cd ultragram/web
npm install
npm run build      # Produktions-Bundle (dist/) – Artefakte aus public/
npm run preview    # z. B. http://localhost:4173
# oder: npm run dev
```

---

## 4. Kann ich die src-Dateien direkt mit `python …` starten?

**Ja, aber nicht mit `python3 src/worldcarto/cli.py`** – die Module
benutzen relative Paket-Importe (`from .config import …`), deshalb muss
Python das **Paket** `worldcarto` im Suchpfad haben:

```bash
# Empfohlen (immer, aus cartogram-pipeline/ heraus):
cd ultragram/cartogram-pipeline
PYTHONPATH=src python3 -m worldcarto.cli <command>

# Einzeiler ohne PYTHONPATH (startet die CLI direkt):
cd ultragram/cartogram-pipeline && python3 -c \
  "import sys; sys.path.insert(0,'src'); from worldcarto.cli import main; raise SystemExit(main(['solve']))"

# Andere Module als Skript (Beispiel):
PYTHONPATH=src python3 -c "from worldcarto.stability import verify_stability; raise SystemExit(verify_stability())"
```

- `python3 -m worldcarto.cli` entspricht `cli.py → main()`; nur
  `cli.py` und `stability.py` haben einen `if __name__ == "__main__"`-
  Einstieg.
- Ein `pip install -e .` ist derzeit nicht nötig/vorgesehen (kein
  `pyproject.toml`); `PYTHONPATH=src` ist der dokumentierte Weg.
- Die Module sind bewusst **Funktionsschichten** (ingest, mesh_io,
  temporal, repair, quality, export, stability, debug) – siehe
  Schrittbeschreibungen in Abschnitt 2.

---

## 5. Konfiguration (configs/)

| Datei | steuert |
|---|---|
| `pipeline.yaml` | Pfade (roh, Natural Earth, Cache, dist, web_public), Jahre, Toleranzen, `min_target_share`, **`data.target_metric`**, Geometrie (CRS, Ausschlüsse, Vereinfachung), Solver-/Übergangs-/Qualitätsparameter |
| `entities.yaml` | Entitätenregister: ids, Anzeigenamen, Quellnamen, Geometrie-Mitglieder, historische Aggregate, OTHER_WORLD |
| `solver.yaml` | Solver-Kette + Flow-Parameter (Gitter, Glättung, Schritte, Toleranzen) |
| `visualization.yaml` | Farbskala, Höhenformel (im Manifest dokumentiert) |

Jede Cache-Stufe hasht die Konfigurationsdateien – Änderungen
invalidieren die betroffenen Caches automatisch.

---

## 6. Qualität & bekannte Grenzen (dokumentiert)

- **p90-Flächenfehler**: 90 % der aktiven Entitäten unter 5 %
  (frühe Jahre 12 % bis `early_years_until`) – Extremfälle sind fast
  ausschließlich Rest-Welt-/Aufstockungs-Entitäten (Panama 1820:
  128 km² Zielfläche, kleiner als eine Gitterzelle).
- **Faltflächen**: eingeklappte Innenflächen bleiben sichtbar
  dokumentiert, wenn sie unter dem Schwellwert liegen (keine
  heimliche „Korrektur"); der Solver optimiert sie weg.
- **Reparatur-Design**: siehe README-Abschnitt Reparatur – „nur
  reparieren, wenn es besser ist", Hysterese über Jahre, dokumentierte
  Skip-Fälle.
- **OTHER_WORLD**: ein Zielgewicht (Rest-Bevölkerung), aber viele
  Länderformen – die Anteile *innerhalb* der Rest-Welt folgen der
  geografischen Form, nicht einzelnen Datenwerten (dafür gibt es
  keine Datengrundlage).
