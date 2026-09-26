# Finaler Implementierungsplan – Animated Energy Cartogram

## 1. Zielbild

Das Projekt zeigt die Entwicklung von Bevölkerung und Energieverbrauch von 1820 bis 2020 als interaktive, zeitabhängige Visualisierung.

Die Produktionsarchitektur bleibt offline-first:

- Python bereitet Daten, Geometrien und Cartogramm-Keyframes vollständig vor.
- TypeScript/JavaScript übernimmt Darstellung, Interpolation und Interaktion.
- Der Browser führt keine Cartogramm-Berechnungen durch.

Die Hauptansicht wird als flache beziehungsweise leicht perspektivische 2.5D-Cartogramm-Weltkarte umgesetzt. Eine drehbare 3D-Erde kann später als ergänzende geografische Referenzansicht hinzukommen, ist aber nicht die primäre Cartogramm-Darstellung.

---

## 2. Datenbasis

Verwendete Datei:

```text
country_populationshare_energypercapita.csv
```

Erwartetes bereinigtes Schema:

```text
Country
Macroarea
Year
Population
Energy_consumption
World_population
World_share
Per_capita_energy_consumption
```

Die Datei enthält jährliche Werte von 1820 bis 2020. Eine zusätzliche zeitliche Interpolation der Quelldaten ist daher nicht erforderlich. Interpolation wird nur im Renderer verwendet, um visuell flüssig zwischen zwei Jahres-Keyframes überzublenden.

### Verbindliche Annahmen

- `Population` ist je Land und Jahr bereinigt.
- `World_population` enthält je Jahr den korrekten Weltwert.
- `World_share` wurde als `Population / World_population` berechnet.
- Einheiten sind über alle Jahre konsistent.
- Doppelte Schlüssel `(Country, Year)` sind nicht zulässig.

### Minimalvalidierung vor dem Build

```python
assert required_columns_present
assert unique(Country, Year)
assert Year.min() == 1820
assert Year.max() == 2020
assert Population >= 0
assert Energy_consumption >= 0 or is_missing
assert World_population > 0
assert abs(World_share - Population / World_population) < tolerance
```

Zusätzlich werden je Jahr geprüft:

```python
represented_share = sum(World_share)
remainder_share = 1.0 - represented_share
```

Falls der bereinigte Datensatz bereits `OTHER_WORLD` enthält, muss dessen Anteil dem `remainder_share` entsprechen. Andernfalls erzeugt die Pipeline diese Entität.

---

## 3. Entscheidung zur 3D-Darstellung

## Empfehlung: Cartogramm in 2.5D, Globus nur ergänzend

Die eChalk-Darstellung ist eine gute Referenz für:

- Drag-to-rotate
- Zoom
- klare Layer-Auswahl
- politische und statistische Kartenansichten
- WebGL-basierte Exploration

Sie wird nicht nachgebaut oder kopiert.

Für dieses Projekt ist ein reiner Globus nicht die beste Hauptansicht. Ein Cartogramm verändert Länderflächen nach Bevölkerungsanteilen. Diese Verzerrung lässt sich auf einer flachen, flächentreuen Projektion klarer lesen und zeitlich stabiler animieren als auf einer Kugel.

### Primäre Ansicht

**2.5D Continuous Cartogram**

- X/Y: vorberechnete Cartogramm-Geometrie
- Fläche: `World_share`
- Farbe: `Per_capita_energy_consumption`
- Höhe: standardmäßig `Energy_consumption` oder optional eine normalisierte Energiekennzahl
- Zeit: 1820 bis 2020

### Ergänzende Ansicht

**Reference Globe**

- unverzerrte Ländergeometrien auf einer Kugel
- Farbe nach ausgewählter Kennzahl
- Rotation und Zoom wie bei etablierten interaktiven Erdgloben
- Umschaltung zwischen `Geografie` und `Cartogramm`

Der Globus dient der räumlichen Orientierung. Das Cartogramm bleibt die analytische Hauptansicht.

### Warum nicht dieselbe deformierte Geometrie auf einen Globus kleben?

- Flächenverzerrung ist auf der Kugel schwerer vergleichbar.
- Extrusionen über einer gekrümmten Oberfläche überdecken sich schneller.
- Länder an der Rückseite sind nicht gleichzeitig sichtbar.
- Eine stabile Animation historischer Cartogramm-Geometrien ist auf der Ebene einfacher zu prüfen.
- Die flächentreue Equal-Earth-Ausgangsprojektion passt direkt zum Cartogramm-Solver.

---

## 4. Wiederverwendung des vorhandenen Python-Prototyps

Aus `cartogram_macroarea_temporal_3a.py` werden folgende Teile modularisiert und weiterverwendet:

- Natural-Earth-Import mit lokaler Quelle und Fallback
- ISO3- und Makroregion-Zuordnungen
- historische Aggregate wie USSR, Yugoslavia und Czechoslovakia
- Geometrievalidierung und Projektion
- jährliche Datenloader
- Cache-Grundidee
- Largest-Remainder-Verteilung
- Warm-Start als zusätzlicher Kandidat
- GeoPackage- und JSON-Zwischenartefakte
- Debug- und Regression-Rendering mit Matplotlib

### Legacy Tile Mode

Der vorhandene Tile-Algorithmus bleibt als separater Modus erhalten:

```text
legacy_tiles
```

Er ist geeignet für:

- visuelle Vergleiche
- schnelle Prototypen
- Regressionstests
- alternative kachelbasierte Darstellung

Er ist nicht der primäre Produktions-Solver für das kontinuierliche Cartogramm.

---

## 5. Python-Pipeline

## 5.1 Ingest

```text
CSV → validierter DataFrame → Parquet
```

Kanonischer Schlüssel:

```text
entity_id + year
```

Zu erzeugende Felder:

```text
entity_id
country_name
macroarea
year
population
energy_consumption
world_population
world_share
per_capita_energy_consumption
is_other_world
```

## 5.2 Entitätenregister

Die Mappings aus dem Prototyp werden nach `configs/entities.yaml` übertragen.

Je Entität:

```yaml
- id: SUN
  display_name: USSR and former USSR
  source_names:
    - F. USSR
  geometry_members:
    - RUS
    - UKR
    - BLR
  historical_aggregate: true
```

## 5.3 Ausgangsgeometrie

- vollständige Natural-Earth-Geometrie laden
- Geometrien reparieren
- Entitäten nach Registry dissolven
- fehlende Gebiete zu `OTHER_WORLD` zusammenfassen
- in eine flächentreue Projektion überführen
- gemeinsame Grenzen aufbauen
- einmalig vereinfachen und segmentieren

Bevorzugte Projektion:

```text
Equal Earth
```

`EPSG:6933` aus dem bestehenden Prototyp kann für Tests und Vergleichsläufe erhalten bleiben.

## 5.4 Solver-Abstraktion

```python
class CartogramSolver(Protocol):
    def solve(self, geometry, targets, config):
        ...
```

Implementierungen:

```text
cartogram_cpp    # Produktion
carto_flow       # Fallback und Benchmark
legacy_tiles     # recycelter Tile-Prototyp
```

## 5.5 Kanonisches Mesh

Ein gemeinsames Mesh wird einmal erzeugt:

- feste Vertex-IDs
- feste Dreiecksindizes
- feste Regionszuordnung
- gemeinsame Grenzvertices
- keine jährliche Neutriangulierung

## 5.6 Jahres-Keyframes

Für jedes Jahr 1820 bis 2020:

1. Zielgewicht `World_share` laden.
2. `OTHER_WORLD` prüfen oder ergänzen.
3. Direct Solve vom kanonischen Ausgangszustand erzeugen.
4. Optional Warm-Start vom Vorjahr erzeugen.
5. Beide Kandidaten validieren.
6. Besten gültigen Kandidaten speichern.

### Qualitätskriterien

- keine invertierten Dreiecke
- keine neuen Selbstüberschneidungen
- unveränderter Adjazenzgraph
- Flächenfehler unter konfigurierter Schwelle
- identische Vertex-Anzahl und Reihenfolge
- plausible Verschiebung gegenüber dem Vorjahr

### Übergangsprüfung

Zwischen zwei Jahres-Keyframes wird die lineare Vertex-Interpolation ebenfalls geprüft. Falls ein Übergang Dreiecksinversionen verursacht, erzeugt Python einen zusätzlichen Zwischen-Keyframe.

---

## 6. Exportvertrag für TypeScript

```text
dist/cartogram/v1/
├── manifest.json
├── entities.json
├── topology.bin
├── positions.f32
├── values.f32
├── labels.f32
├── indices.u32
├── surface_vertex_to_canonical.u32
├── region_draw_ranges.u32
├── boundary_rings.u32
├── flags.u8
└── quality.parquet
```

### `values.f32`

Enthält mindestens:

```text
population
world_share
energy_consumption
per_capita_energy_consumption
```

### `manifest.json`

Enthält:

- Datenversion
- Jahre
- Dimensionen und Array-Reihenfolge
- CRS und Projektion
- Einheiten
- Solver und Solver-Version
- Konfigurations-Hashes
- Input-Hashes
- Prüfsummen aller Artefakte

---

## 7. TypeScript-/JavaScript-Renderer

Empfohlener Stack:

```text
TypeScript
Three.js
React Three Fiber, falls React verwendet wird
WebGL2, optional später WebGPU
```

## 7.1 Gemeinsamer Timeline-State

```ts
interface TimelineState {
  year0: number;
  year1: number;
  t: number;
  playing: boolean;
  speed: number;
}
```

```ts
const xy = lerp(positionYear0, positionYear1, t);
const value = lerp(valueYear0, valueYear1, t);
```

## 7.2 Flat Mode

- orthografische oder leicht perspektivische Kamera
- Cartogramm-Flächen
- Ländergrenzen
- Farbe nach ausgewählter Kennzahl
- keine Extrusion

## 7.3 Cinematic 2.5D Mode

- identische XY-Positionen und Dreiecksindizes
- Extrusion entlang der Z-Achse
- Seitenwände pro Region
- weiche Beleuchtung und Schatten
- begrenzte Höhe zur Vermeidung visueller Überdeckung
- automatische Kamerafahrten nur im Story-Modus

Empfohlenes Standardmapping:

```text
Fläche = World_share
Farbe  = Per_capita_energy_consumption
Höhe   = Energy_consumption, logarithmisch oder robust normalisiert
```

Population wird nicht gleichzeitig nochmals als Höhe kodiert, weil sie bereits die Fläche bestimmt.

## 7.4 Reference Globe

- statische, unverzerrte Ländergeometrien
- Farbe nach derselben aktiven Kennzahl
- gleiche Timeline und Tooltips
- frei drehbar und zoombar
- keine Cartogramm-Extrusion im ersten Release

## 7.5 Interaktion

- Play/Pause
- Zeitslider 1820 bis 2020
- Geschwindigkeitswahl
- Flat / 2.5D / Globe Umschalter
- Kennzahl-Umschalter
- Hover und Auswahl eines Landes
- Detailpanel mit Zeitreihe
- Reset Camera

---

## 8. Skalierung der visuellen Kennzahlen

Globale Rohwert-Minima und -Maxima über 201 Jahre führen wahrscheinlich zu geringer Differenzierung früher Jahre. Deshalb werden Skalen explizit konfiguriert.

### Farbe

Für `Per_capita_energy_consumption`:

- sequenzielle Farbskala
- wahlweise logarithmische oder Quantil-basierte Normalisierung
- Legende zeigt die tatsächlichen Einheiten

### Höhe

Für `Energy_consumption`:

```python
height = log1p(value) / log1p(global_reference)
```

Alternativ robuste Perzentil-Skalierung. Die gewählte Transformation wird im Manifest dokumentiert.

### Fläche

Die Fläche bleibt ausschließlich solverbasiert proportional zu `World_share`.

---

## 9. Projektstruktur

```text
cartogram-pipeline/
├── configs/
│   ├── entities.yaml
│   ├── pipeline.yaml
│   ├── solver.yaml
│   └── visualization.yaml
├── data/
│   ├── raw/
│   ├── intermediate/
│   └── reference/
├── src/worldcarto/
│   ├── ingest.py
│   ├── schema.py
│   ├── entities.py
│   ├── geometry.py
│   ├── topology.py
│   ├── temporal.py
│   ├── triangulate.py
│   ├── quality.py
│   ├── export.py
│   ├── cli.py
│   └── solvers/
│       ├── cartogram_cpp.py
│       ├── carto_flow.py
│       └── legacy_tiles.py
├── tests/
├── build-cache/
└── dist/

web/
├── src/
│   ├── data/
│   ├── renderers/
│   │   ├── FlatCartogram.ts
│   │   ├── ExtrudedCartogram.ts
│   │   └── ReferenceGlobe.ts
│   ├── timeline/
│   ├── interaction/
│   └── ui/
└── public/cartogram/v1/
```

---

## 10. Implementierungsphasen

### Phase 1 – Daten und Bestandscode

- bereinigtes CSV validieren
- kanonisches Parquet erzeugen
- Mappings aus dem Prototyp nach YAML übertragen
- Natural-Earth-Loader modularisieren
- Tile-Code nach `legacy_tiles.py` verschieben

### Phase 2 – Geometrie und Solver

- vollständige Entitätengeometrien erzeugen
- `OTHER_WORLD` geometrisch aufbauen
- Solver-Interface implementieren
- `cartogram-cpp` integrieren
- ausgewählte Testjahre rechnen

Empfohlene Testjahre:

```text
1820, 1900, 1950, 2000, 2020
```

### Phase 3 – Kanonisches Mesh und Zeitkohärenz

- gemeinsame Topologie erzeugen
- einmalig triangulieren
- Direct- und Warm-Start-Kandidaten vergleichen
- Übergänge validieren
- Qualitätsbericht erzeugen

### Phase 4 – Browserartefakte

- Typed Arrays exportieren
- Manifest und Prüfsummen erzeugen
- Lade- und Speicherverhalten testen

### Phase 5 – Visualisierung V1

- Flat Cartogram
- Cinematic 2.5D Cartogram
- Timeline
- Tooltip und Detailpanel
- Kennzahl-Umschaltung

### Phase 6 – Ergänzende Globe-Ansicht

- Reference Globe
- gemeinsame Timeline
- gleiche Farbskalen und Auswahl
- koordinierter Wechsel zwischen Globe und Cartogramm

### Phase 7 – Story und Export

- kuratierte Kamerafahrten
- Story-Kapitel
- Bild- und Videoexport
- Barrierefreiheit und reduzierte Bewegung

---

## 11. V1-Scope

Verbindlich für den ersten Release:

- bereinigtes CSV als alleinige Faktengrundlage
- kontinuierliches Cartogramm
- `World_share` als Flächengewicht
- Flat- und 2.5D-Modus
- Timeline 1820 bis 2020
- Farbe nach Energie pro Kopf
- optionale Höhe nach Gesamtenergie
- Tooltip, Legende und Länderauswahl
- vollständig offline vorberechnete Geometrien

Nicht Teil von V1:

- physikalische Sonnen- oder Tag-/Nacht-Simulation
- Partikelströme
- animierte Handels- oder Migrationslinien
- deformiertes Cartogramm direkt auf der Kugel
- Echtzeit-Solver im Browser

---

## 12. Endgültige Entscheidung

Wir übernehmen von der eChalk-Referenz die Idee einer leicht verständlichen, dreh- und zoombaren 3D-Erde, aber nur als optionale geografische Referenzansicht.

Die Hauptvisualisierung bleibt ein flaches beziehungsweise 2.5D-extrudiertes, zeitabhängiges Cartogramm. Das ist für die Kernbotschaft eindeutiger:

```text
Fläche zeigt den Anteil an der Weltbevölkerung.
Farbe zeigt Energieverbrauch pro Kopf.
Höhe zeigt den gesamten Energieverbrauch.
Zeit zeigt die Entwicklung von 1820 bis 2020.
```

Damit sind Datenbedeutung, Geometrie und Animation klar getrennt, und derselbe vorberechnete Datensatz kann sowohl für die analytische Flat-Ansicht als auch für die filmische 2.5D-Ansicht verwendet werden.
