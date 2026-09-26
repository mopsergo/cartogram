# Ultragram – Plan: 3D-Kartogramm „Bevölkerungsanteil & Energie pro Kopf, 1820–2020“

Stand: 26.09.2026 · Status: Entwurf zur Entscheidung · Baut auf
[`reduzierter_implementation_plan_v2.md`](reduzierter_implementation_plan_v2.md)
(Architektur) und
[`datasets/world_share_implementation.md`](../datasets/world_share_implementation.md)
(Datenstandard) auf.

---

## 0. Ziel in einem Absatz

Eine Web-App im Stil des eChalk *3D Interactive Earth* (polierte WebGL-Szene,
schwarzer Raum, Drehen/Zoomen mit der Maus, Auto-Rotation, Legende, Menü),
die aber statt eines Globus ein **animiertes 3D-Kartogramm** zeigt:

- **Fläche jedes Landes ∝ Weltbevölkerungsanteil** (`World_share`),
- **Höhe jedes Landes ∝ Energieverbrauch pro Kopf** (`Per_capita_energy_consumption`),
- **Zeitachse 1820–2020** mit Play/Pause, Scrubbing und Tempo,
- **alle Daten vorab offline berechnet** – der Browser interpoliert nur noch
  (Architektur-Prinzip aus Plan v2: „Im Browser finden keine Länder-Joins,
  Projektionen, Polygonreparaturen oder Cartogram-Solves statt“).

Der besondere Reiz – und die Antwort auf die Frage, wie die **Entwicklung
beider Faktoren** zugleich lesbar wird: Bei linearer Höhenskala ist das
**Volumen jedes Landkörpers ∝ Gesamtenergieverbrauch** (Fläche ∝ Bevölkerung
× Höhe ∝ Verbrauch/Kopf). Die Szene zeigt also drei Größen gleichzeitig:
Bevölkerung (Basis), Pro-Kopf-Verbrauch (Höhe), Gesamtverbrauch (Volumen).

---

## 1. Leitbild: Was den eChalk Interactive Earth ausmacht

Analyse der Referenz
(`echalk.co.uk/.../interactiveEarth.html`, Three.js-basiert):

| eChalk-Merkmal | Übernahme in Ultragram |
|---|---|
| WebGL-Globus im schwarzen Raum, sanfte Beleuchtung | 3D-„Kartogramm-Tafel“ im schwarzen Sternenraum (kein Globus, s. 4.2) |
| Menü mit Ansichten (u. a. *Population cartogram* als Worldmapper-Textur) | Menü mit Modi: Farben/Metriken, Ghost-Modus, A/B-Jahre, Story-Kapitel |
| Key/Legend je Ansicht | Legende für Höhe (kWh/Kopf, Skala linear/wurzel/log) + Farbmodus |
| Auto-Rotation als Toggle | Auto-Orbit-Kamera als Toggle, pausiert bei Interaktion |
| Drag = bewegen, Wheel = Zoom, Touch-Pinch | identisch (OrbitControls-Parität) |
| Loading-Dialog, WebGL-Fallback-Dialog, „works best on large screens“ | identisch übernehmen |
| Hover auf Länder (Daten-Overlay) | Hover-Tooltip + Klick-Länderpanel mit Zeitreihen (s. 9.4) |

Nicht übernommen: Globus-Projektion, Ebenen-Texturen (Klima, Tektonik …) –
unser „Layer“ ist die Zeit.

---

## 2. Datengrundlage (Ist-Zustand, geprüft am 26.09.2026)

### 2.1 Datentabelle

`datasets/country_populationshare_energypercapita.csv`
(Regenerator: `datasets/prep_data.py`, aktueller Stand):

```
Country, Macroarea, Year, Population, Energy_consumption,
World_population, World_share, Per_capita_energy_consumption
```

- **72 reelle Entitäten** + **`OTHER_WORLD`** (Rest-Welt, 1 Zeile/Jahr).
  `World_share` summiert pro Jahr auf **exakt 1,0** – der Standard aus
  `world_share_implementation.md` ist umgesetzt. Ohne OTHER_WORLD würden die
  72 Entitäten auf 80,9–94,2 % bleiben; der Rest (1820: 7,6 % → 2020:
  19,1 %) gehört geometrisch zu OTHER_WORLD, sonst bläht der Solver die
  Entitäten künstlich auf.
- Jahre 1820–2020 lückenlos (Ausnahme: Israel erst ab 1950 → vor 1950
  Teil von OTHER_WORLD, s. 7.3).
- `Per_capita_energy_consumption`: 0 … **104.088 kWh/Kopf** (USA 2000);
  1 Zeile mit 0 (Panama 1820). Wertebereich über 5 Dekaden →
  Höhenskalierung zwingend schaltbar.
- Datencuriosa (für Fußnote/Doku, keine „Korrektur“): Kanada/USA starten
  1820 bereits bei ~46 700/29 800 kWh/Kopf (WEC-Methodik inkl. Biomasse).

### 2.2 Geometrie

- Natural Earth **110 m** (`datasets/ne_110m_admin_0_countries.geojson`),
  flächentreu projiziert auf **EPSG:6933** (Plan v2).
- Historische Aggregate als Vereiningung der Mitgliedsländer:
  F. USSR, Czechoslovakia, Yugoslavia, Eritrea & Ethiopia
  (recyceln aus `mopsogram/meshdata.py: SPECIAL`).
- **OTHER_WORLD-Geometrie pro Jahr** = Welt − Vereinigung der im Jahr
  belegten Entitäten (Länder ohne Jahreszeile, z. B. Israel < 1950, fallen
  geometrisch in OTHER_WORLD). Pro Jahr ein eigener geometrischer Zustand.

### 2.3 Vorhandene, recycelbare Bausteine

| Baustein | Ort | Verwendung |
|---|---|---|
| Flow-Kartogramm-Solver (Gastner/Seguy/More PNAS 2018, pure numpy + FFT) | `mopsogram/cartogram.py` | Sekundär-Solver / Fallback, Vertex-Korrespondenz bleibt erhalten |
| **Dekaden-Snapshots (1820–2020, 21 Stück) bereits gecacht** | `mopsogram/cartogram_cache.json` | **Phase-0-Spike sofort möglich**, ohne neue Solves |
| Mesh/Prismen-Bau, SPECIAL-Mapping, Höhenmodi | `mopsogram/meshdata.py` | Vorlage für Export & Höhenformeln |
| Dash/Plotly-Referenz-App | `mopsogram/app.py` | Nur interner Vergleich/Regression, nicht Produkt |
| Tile-Cartogramm-Prototyp (force-directed) | `cartogram_macroarea_temporal_3a.py` | Optionaler Stil-Modus „Tiles“ (Plan v2: `legacy_tiles`) |
| Playwright-QA-Skripte | `mopsogram/qa/*.mjs` | Muster für Phase 6 |
| Architekturplan | `reduzierter_implementation_plan_v2.md` | verbindlich: Python offline → Binärartefakte → TS-Renderer |

---

## 3. Visualisierungsprinzip: zwei Faktoren in einem Raum

```
Fläche_i(t)  ∝ World_share_i(t)          (Kartogramm-Zielgewicht)
Höhe_i(t)    ∝ f(Per_capita_i(t))         f ∈ {linear, sqrt, log}
Farbe_i(t)   ∈ {Makroregion, kWh-Gradient, Δ seit Basisjahr}
Volumen_i(t) ∝ Gesamtverbrauch_i(t)       (exakt bei f = linear)
```

- **Standard: f = sqrt** (Lesbarkeit, wie Mopsogram), Toggle auf linear/log.
- Bei linear gilt die Volumen-Identität – als Erklär-Callout („Das Volumen
  ist der Gesamtverbrauch“) einblendbar.
- Andere Werte im selben Jahr bleiben vergleichbar, weil pro Jahr **ein
  gemeinsamer kartogrammischer Zustand** existiert (kein Springen der
  Grundrisse zwischen Ländern/Metriken).
- Höhenachsen-Legende mit Tick-Werten in kWh/Kopf (wie eChalk-Key, aber
  kontinuierlich).

---

## 4. Darstellungs- & Projektionsvarianten („Welche Möglichkeiten haben wir?“)

Bewertet nach: Korrektheit der Kartogramm-Aussage, Lesbarkeit der
Entwicklung, Aufwand. R = Empfehlung Produktionsreifograd.

### 4.1 Kartogramm-Tafel im Raum („floating board“) — **Primärmodus (R: hoch)**

Die verzerrte Weltkarte als flache Platte, frei im schwarzen Sternenraum
schwebend; Länder als extrudierte Prismen; Kamera orbitet frei (wie eChalk,
nur eben statt kugelförmig).

- Voll kompatibel mit flächenproportionaler Kartogramm-Geometrie.
- Spiegelbild unter der Platte (einfache Fake-Reflexion: gespiegelte
  Geometrie bei ~10 % Opazität) → edle „Installations“-Anmutung ohne
  Raytracing-Kosten.
- Höhen-Entrauschen durch weiche Schattierung/Kantenlicht statt harter
  Schatten; optionales Bloom nur auf Prismenoberkanten (Nächste-Phase).

### 4.2 Kartogramm-Globus (à la eChalk *Population cartogram*) — **optionaler Wow-Modus (R: mittel, mit Vorbehalt)**

eChalk klebt die Worldmapper-Kartogrammkarte als **Textur auf den Globus**.
Analog: Kartogramm-Rasterung offline → equirectangular Textur (mit Ozean
aufgefüllt) auf Kugel, Höhe optional als Displacement.

- Pro: ikonisch, maximal „eChalk-like“.
- Contra: Planares Kartogramm füllt die Equirect-Fläche nicht → Naht/
  Verzerrung am Rand; Höhen verlieren Parallaxe (nur Displacement-Bump);
  inhaltlich ist die Kugelform für Kartogramme ungewöhnlich.
- **Empfehlung:** erst nach Kernmodus; wenn Globus, dann als dezenter
  Zweitmodus, nicht als Hauptansicht.

### 4.3 Morph-Modus „Echte Geographie ↔ Kartogramm“ — **starkes Entwicklungswerkzeug (R: hoch)**

Schieberegler/Blende zwischen unverzerrter NE-Karte und Kartogramm desselben
Jahres. Macht sichtbar, *wie weit* die Welt von ihrer geographischen Fläche
wegwandert (China/Indien wachsen, Kanada/Russland schrumpfen). Technisch
kostenlos, weil beides dieselbe Vertex-Topologie hat (GPU-Morph, s. 5.2).

### 4.4 Geister & Spuren — **Entwicklungs-Gefühl (R: mittel)**

- *Jahres-Ghost:* Umriss eines wählbaren Vergleichsjahres (z. B. 1820) als
  halbtransparenter Drahtgitter-Layer.
- *Bewegungsspuren:* Zentroid jedes Landes hinterlässt eine Spur über die
  Zeit (zeigt Drift der Grundrisse, z. B. Afrikas Flächenwachstum).

### 4.5 A/B-Jahressplit — **Vergleich ohne Zeitreise (R: mittel)**

Zwei Zeitpunkte nebeneinander (z. B. 1820 | 2020) oder als geteilte Szene
mit gemeinsamer Kamera. Direkter „Vorher/Nachher“-Effekt; gut für
Präsentationen/Screenshots.

### 4.6 Begleit-Chart (Bump/Race) — **quantitative Absicherung (R: mittel)**

Seitenpanel wie in Mopsogram, aber als synchronisierte
Ranking-Verlaufskurve („Bump Chart“) der Top-N Länder nach World_share und
nach kWh/Kopf; spielt mit dem Jahres-Cursor mit. Macht die Entwicklung auch
zahlenlesbar, ohne die 3D-Szene zu belasten.

### 4.7 Story-Modus „Zeitreise“ — **geführte Erzählung (R: niedrig, aber hochwirksam)**

Kapitel mit Kamerafahrten + Caption-Overlays (Auto-Play mit Pausen):

1. *Vor der Industrialisierung* (1820): riesige Flächen Asiens, fast flache
   Welt, frühe Spitzen UK/USA.
2. *Industrialisierung* (~1850–1900): Westeuropa/Nordamerika wachsen in die
   Höhe.
3. *Weltkriege & Zwischenkrieg* (1914–1945): Einbrüche, UdSSR-Anstieg.
4. *Nachkriegsboom* (1950–1970): genereller Höhenanstieg, Flächenverschiebung
   Richtung „Rest der Welt“.
5. *Ölzeitalter* (1970er): Nadelspitzen am Golf (S. Arabia, Libyen).
6. *Asiens Aufstieg* (2000–2020): Chinas/Indiens Türme bei gleichzeitig
   stabiler Riesenfläche.

Kapitel sind reine Daten (Jahr, Kamera-Pose, Text) – kein Code pro Kapitel.

### 4.8 Nicht empfohlen

- Kartogramm **auf** dem Globus als Hauptansicht (4.2-Risiken).
- Echte Geographie + Höhe **ohne** Flächenverzerrung als Hauptansicht
  (verletzt die Kernanforderung Fläche ∝ Populationsanteil; nur als
  Morph-Ziel in 4.3 sinnvoll).
- Tile-/Hex-Kartogramm als Hauptansatz (existiert als Prototyp; behalten als
  optionalen Stil-Modus `legacy_tiles` gemäß Plan v2).

---

## 5. Renderer-Entscheidung (inkl. MapLibre-Bewertung)

### 5.1 Entscheidungsmatrix

| Kriterium | **Three.js (primär empfohlen)** | MapLibre GL JS | deck.gl | Plotly/Dash (Ist) |
|---|---|---|---|---|
| eChalk-Gefühl (freie Orbit-Kamera, schwarzer Raum, Auto-Rotate) | ✔ volle Kontrolle | ◐ Globe/Pitch/Bearing, aber karten-zentriert | ◐ OrbitView | ✖ |
| Morphing der Kartogramm-Geometrie über Jahre | ✔ **GPU**: 2 Positions-Attribute + `uMix`-Uniform, statische Buffer, 60 fps garantiert | ✖ kein Vertex-Morphing → `setData()` je Frame (Geometrie-Re-Index je Frame, ~10k Vertices machbar, aber ruckelig/GC-Last) | ✔ Attribute-Updates je Frame (CPU-seitig) | ◐ (Restyle-Tricks, Ist in Mopsogram) |
| Höhen-Animation | ✔ Uniform/Attribut, beliebig | ✔ `fill-extrusion-height` ist data-driven; je Frame via `feature-state` (72 Features) ok | ✔ `elevation`-Attribut | ◐ |
| Extrusions-Look (Prismen) | ✔ selbst bauen (Schaufel/Seitenwände), voller Einfluss | ✔ `fill-extrusion` (flache Deckel, feste 3-Licht-Beleuchtung) | ✔ PolygonLayer extruded | ✖ (Mesh3d-Bastel) |
| Postprocessing (Bloom, Glow, SSAO) | ✔ (EffectComposer) | ✖ | ◐ | ✖ |
| Hover/Picking, Tooltips | ✔ Raycast/GPU-Picking | ✔ `queryRenderedFeatures` | ✔ | ◐ |
| Labels/Legende | selbst (troika-three-text, HTML-Overlays) | ✔ native Kollisions-Labels – aber: Kartogramm-Koordinaten sind keine Kartenkoordinaten, Map-Features (Kacheln, POIs) unbrauchbar | selbst | selbst |
| Aufwand | mittel-hoch (eigene Szene) | niedrig-mittel (aber Morphing-Bastel) | mittel | – |
| Status | Ziel gemäß Plan v2 („TypeScript-Renderer“) | zusätzliche Option | zusätzliche Option | nur Referenz |

### 5.2 Der entscheidende technische Punkt (Warum Three.js)

Mit **fixer Vertex-Topologie über alle Jahre** (Plan v2, kanonisches Mesh)
ist die Jahres-Animation ein reiner GPU-Vorgang:

```glsl
// Vertex-Shader (Skizze)
attribute vec3 posA;    // Keyframe Jahr A
attribute vec3 posB;    // Keyframe Jahr B
uniform float uMix;     // 0..1 zwischen A und B (easing im JS)
// Höhe analog als 2 Skalar-Attribute + uMix
vec3 p = mix(posA, posB, uMix);
```

- Buffer bleiben statisch; beim Überschreiten einer Keyframe-Grenze werden
  nur die zwei Attribute umgehängt (Buffer-Swap, kein Re-Upload der Szene).
- Scrubbing ist damit **instantan in beide Richtungen** – genau das
  eChalk-Gefühl („drag to move, wheel to zoom“ + our timeline).

### 5.3 MapLibre GL JS: ehrliche Einschätzung

**Was gut funktioniert:** `fill-extrusion` liefert sofort hübsche Prismen
mit Licht; Höhen lassen sich ohne `setData` über `feature-state` animieren;
v5 hat eine echte Globus-Projektion (falls 4.2 gebaut wird); Atmosphäre/Sky
und Bedienung sind poliert; Lizenz BSD.

**Was nicht funktioniert:** MapLibre kann keine Vertex-Morphing-Animation –
die Kernszene (Kartogramm wandelt sich Jahr für Jahr) müsste über
`GeoJSONSource.setData()` je Frame gespeist werden. Das kollidiert mit
MapLibre + GC-Last; die „Karten“-Stärken (Kacheln, Projektionen,
Label-Kollision, Terrain) bringen uns beim Kartogramm nichts, weil die
Koordinaten ohnehin keinem Kartenraum mehr folgen.

**Fazit MapLibre:** nicht als primäre Engine, aber als **optionaler
„Karten-Modus“** (flache Ansicht mit ~60° Pitch, `fill-extrusion`, Höhen via
`feature-state`, Keyframe-Wechsel je Jahr statt Frame-Morphing) aus
denselben Exportartefakten (GeoJSON-Variante, s. 7.5) machbar – Aufwand
klein, Entscheidung nach Kernmodus (offene Frage O2).

**Empfehlung: Three.js (Vite + TypeScript) als primärer Renderer.** MapLibre
als Zweitmodus optional; deck.gl und Plotly nicht für die Zielszene.

---

## 6. Kartogramm-Solver & Keyframe-Dichte

### 6.1 Solver-Optionen

| Solver | Pro | Contra | Rolle |
|---|---|---|---|
| `mopsogram/cartogram.py` (PNAS 2018, numpy) | vorhanden, geprüft, Vertex-Korrespondenz per Bau, keine externen Abhängigkeiten | Geschwindigkeit × 201 Jahre noch ungemessen | **Fallback + Benchmark** |
| **`cartogram-cpp`** (Gastner et al., C++) | sehr schnell (Sekunden/Jahr), robust, CLI | externes Binary, Integration/Aufruf | **primärer Kandidat** |
| GoCart (R) | aktuell, schnell, gut dokumentiert | R-Abhängigkeit | Alternative |
| legacy tiles (Prototyp) | vorhanden | Kachel-Optik, kein flächenkontinuierlicher Solver | optionaler Stil-Modus |

Einheitliches Solver-Interface gemäß Plan v2:

```python
class CartogramSolver(Protocol):
    def solve(self, geometry, targets, config) -> CartogramResult: ...
```

### 6.2 Keyframe-Dichte (Entscheidung nach Messung)

- **Ideal: 1 Keyframe pro Jahr** (201 Solves) → Browser interpoliert nur
  zwischen Nachbarjahren; Scrubbing 1-Jahres-genau.
- **Fallback: alle 5 Jahre** (41 Solves) + Interpolation; Dekaden (21)
  reichen nachweislich für flüssige Animation (Mopsogram-Praxis), verlieren
  aber Details bei Einzeljahren.
- Höhe (kWh/Kopf) und Werte ohnehin **jährlich** aus der CSV – unabhängig
  von der Kartogramm-Dichte.

### 6.3 Qualitäts-Gates je Keyframe (aus Plan v2 übernommen)

- Flächenfehler je Land < konfigurierbare Schwelle (z. B. 95 % der Entitäten
  < 5 %); Bericht je Jahr (`quality.parquet`).
- Keine Selbstüberschneidungen / invertierten Dreiecke.
- Plausibler Übergang zum Vorjahr (Sprungweite der Vertices < Grenzwert) –
  ersetzt den Warm-Start-Drift-Ansatz: **gelöst wird vom kanonischen
  Ausgangszustand**, nicht vom Vorjahr (Plan v2).
- Da die flow-basierten Solver die **Eingabe-Polygon-Vertices integrieren**,
  bleibt die Vertex-Korrespondenz zwischen allen Jahren erhalten – die
  Grundlage für GPU-Morphing und Interpolation.

---

## 7. Offline-Pipeline (Python) – baut Plan v2 weiter aus

### 7.1 Module (Projektstruktur gemäß Plan v2)

```
ultragram/pipeline/
├── configs/            entities.yaml, pipeline.yaml, solver.yaml
├── src/worldcarto/
│   ├── ingest.py        # CSV-Load + Validierung (Summe 1.0 je Jahr!)
│   ├── entities.py      # SPECIAL + OTHER_WORLD-Mitgliedschaft je Jahr
│   ├── geometry.py      # NE-Import, EPSG:6933, Repair
│   ├── other_world.py   # Welt − belegte Entitäten, je Jahr
│   ├── topology.py      # kanonisches Mesh, feste Vertex-Indizes
│   ├── temporal.py      # Jahresliste, Warm-Start-Kandidaten, Gates
│   ├── triangulate.py   # einmalige Triangulierung (Deckel + Wände)
│   ├── export.py        # Binärartefakte + GeoJSON + manifest.json
│   ├── quality.py       # Flächen-/Topologie-Prüfungen, Bericht
│   ├── cli.py
│   └── solvers/         # cartogram_cpp.py, carto_flow.py, legacy_tiles.py
```

### 7.2 Ablauf je Build

1. `ingest`: CSV laden; harte Prüfung `Σ World_share ≈ 1.0` je Jahr
   (Abbruch statt stiller Normierung).
2. `entities`: 72 Entitäten + SPECIAL-Vereinigungen + **OTHER_WORLD je
   Jahr** (Population aus CSV, Geometrie aus `other_world`).
3. `geometry/topology`: einmalig kanonisches Mesh (feste Indizes,
   gemeinsame Grenzen, Triangulierung inkl. Seitenwände für Prismen).
4. `temporal` × Solver: Keyframes je Jahr (bzw. alle 5 Jahre) vom
   kanonischen Startzustand; Qualitäts-Gates 6.3.
5. `export`: Artifacts (7.4/7.5) + `manifest.json` (Jahre, Dichte,
   Solver-Version, Daten-Hashes, Prüfsummen – Cache-Key gemäß Plan v2).

### 7.3 Sonstige-Region-Logik (wichtig, sonst falsche Flächen)

Länder **ohne Datenzeile im Jahr** (Israel < 1950) gehören in jenem Jahr
sowohl wertmäßig (so macht es `prep_data.py` bereits) als auch
**geometrisch** zu OTHER_WORLD. Damit bleibt die Weltabdeckung vollständig
und das Kartogramm korrekt. OTHER_WORLD wird gerendert als flache, dunkelgraue
Platte „Rest der Welt · keine Daten“ (Höhe 0).

### 7.4 Browser-Artefakte (Zielformat, Erweiterung um Ansichts-Bedürfnisse)

```
dist/cartogram/v1/
├── manifest.json          # Jahre, Dichte, BBox, Skalen, Hashes
├── entities.json          # Namen, Makroregion, Label-Anker
├── topology.bin           # Indizes, Ring-/Wand-Triangulierung (statisch)
├── keyframes/
│   ├── pos_YYYY.f32       # XY je Vertex (kartogrammisch) – bzw. int16 quantisiert
│   ├── coast_YYYY.f32     # Umriss-Linien (Ghost-/Referenzlayer)
│   └── values_YYYY.f32    # World_share, kWh/Kopf (für Höhe + Farben)
├── geography.f32          # unverzerrte Referenz (für Morph-Modus 4.3)
└── geojson/keyframes/     # optionale GeoJSON je Jahr für MapLibre-Modus
```

### 7.5 Größenbudget & Ladestrategie (erste Abschätzung)

- Vertices nach 0,18°-Vereinfachung: ~15–20 k (inkl. Küstenlinien) →
  `pos` float32 ≈ 140–190 KB/Jahr, **quantisiert int16 ≈ 60–80 KB/Jahr**.
- Worst case 201 Jahres-Keyframes quantisiert: **~12–16 MB** + Werte
  (vernachlässigbar) → insgesamt im Rahmen eines Streamings.
- Ladestrategie: Manifest + Dekaden-Gerüst zuerst (Start in <2 s), feine
  Jahres-Keyframes im Hintergrund nachladen (Range-Requests), Playhead
  nutzt Gerüst bis Details da sind.

---

## 8. Frontend-Architektur (TypeScript)

```
ultragram/app/            # Vite + TypeScript + Three.js
├── index.html
├── src/
│   ├── main.ts           # Boot: Loading-Dialog → Artefakte laden → Szene
│   ├── artifacts/        # Loader (manifest, typed arrays), Cache/Lazy-Ranges
│   ├── scene/            # Board, Prismen-Mesh (GPU-Morph), Geister, Spiegel,
│   │                     #   Sternenfeld, Grid, Postprocessing
│   ├── anim/             # Timeline-Store, Easing, Keyframe-Attribute-Swap
│   ├── interact/         # OrbitControls, Auto-Rotate, Raycast/Picking
│   ├── ui/               # Menü, Zeitleiste, Legenden, Tooltip, Länderpanel,
│   │                     #   A/B-Split, Story-Overlay, WebGL-Fallback
│   └── state/            # Modus: Metrik/Skala/Farben/Ghost/Jahr…
└── tests/ + qa/           # Playwright (Mopsogram-Muster)
```

- **Ein** Prismen-Mesh mit fixer Topologie; zwei Positions-/Höhen-Attribute;
  `uMix` je Frame → Jahr. Materialien: Deckel farbig, Wände abgedunkelt,
  OTHER_WORLD mattgrau.
- Kamera: Auto-Orbit (Toggle, pausiert bei Interaktion), Presets
  (Welt, Europa, Asien, Golf), sanftes Damping – eChalk-Parität.
- Labels: Deko-Beschriftung Top-N + Hover-Callout (troika-three-text oder
  HTML-Overlay); Kollisionsregel: nur wenn Grundrisch groß genug.
- Farb-Shader: Makroregion (Default, Palette aus Mopsogram), kWh-Gradient,
  Δ-seit-Basisjahr (dividierend Rot↔Blau) – umschaltbar ohne Neubau.
- Fallback: WebGL-Check → Dialog (wie eChalk) + Link auf eine statische
  PNG-Folge (offline aus der Pipeline renderbar).

---

## 9. Interaktion & UI-Spezifikation (eChalk-inspiriert)

1. **Zeitleiste 1820–2020** (zentrale Steuerung): Play/Pause, Scrubbing
   (pausiert Auto-Play), Tempo (0,5–10 Jahre/s), Jahres-Badge, Ära-Marker.
2. **Welt-Kennzahlen-Ticker:** Weltbevölkerung, Ø kWh/Kopf, Gesamtverbrauch
   des Jahres (aus `World_population` / CSV).
3. **Hover-Tooltip:** Land, Makroregion, World_share %, kWh/Kopf, Rang.
4. **Klick → Länderpanel (Entwicklungs-Fenster):** zwei synchron laufende
   Sparklines 1820–2020 (World_share, kWh/Kopf) + Jahresmarker; mehrere
   Länder pinnbar. *Dies ist das direkte Antwort-Element auf die
   „Entwicklung beider Faktoren“-Frage.*
5. **Legende:** Höhenskala (linear/sqrt/log) mit kWh-Ticks + aktive
   Farbskala + Makroregionen-Chips.
6. **Menü (eChalk-artig, Icon-Kacheln):** Modi – Farben, Ghost an/aus,
   A/B-Jahre, Morph-Regler Geographie↔Kartogramm, Story-Kapitel, optional
   MapLibre-Kartenmodus / Tile-Stil / Globus.
7. **Dialoge:** Loading (Progress der Artefakte), WebGL-Fehler, Hinweis
   „am besten auf großem Bildschirm“, Kurz-Anleitung (Drag/Wheel/Pinch).
8. Tastatur: Space = Play/Pause, ←/→ = Jahr, 1–9 = Kapitel; Touch: Pinch-
   Zoom, Drag-Rotation (eChalk-Parität).

---

## 10. QA & Abnahme

- **Pipeline-Tests:** Share-Summen, Entitätenabdeckung je Jahr, Flächenfehler
  (Gates 6.3), Vertexzahl/Indizes identisch über alle Keyframes.
- **App-QA (Playwright, Mopsogram-Muster):** Render-Screenshots je Ära
  (1820/1870/1913/1950/1973/2000/2020), Scrubbing- und Play-Tests,
  Tooltip/Panel-Tests, WebGL-Fallback-Test, Mobile-Viewport-Test.
- **Performance-Budget:** 60 fps (M1/MacBook-Air-Klasse), Start < 5 s bis
  erste Szene, Artefakt-Download ≤ ~16 MB (7.5).

---

## 11. Meilensteine

### Phase 0 – Renderer-Spike (1–2 Tage) ← sofort möglich
Existierende **Dekaden-Snapshots** (`mopsogram/cartogram_cache.json`) →
Three.js-Tafel mit GPU-Morph, Orbit-Kamera, Höhen aus CSV, Play/Scrub.
**Abnahme:** flüssige 60-fps-Animation 1820–2020 über 21 Keyframes;
Go/No-Go Renderer.

### Phase 1 – Pipeline-Bootstrap (3–5 Tage)
Module aus Plan v2 anlegen; Solver-Messung (eine Dekade): Zeit/Jahr für
`carto_flow` vs. `cartogram-cpp` → Keyframe-Dichte entscheiden;
entities.yaml + OTHER_WORLD-Geometrie; Export v1 (Dekaden) + Manifest.

### Phase 2 – Keyframes & Gates (1–3 Tage Rechenzeit + 2 Tage Ausbau)
Alle Jahre lösen (bzw. 5-Jahres-Raster), Qualitätsbericht, Export v2
(quantisiert, Lazy-Ranges).

### Phase 3 – App-Kern (1 Woche)
Timeline-Store, Attribute-Swap, Legenden, Farbmodi, Tooltip, Klick-Panel mit
Sparklines, Loading/Fallback-Dialoge, Tastatur/Touch.

### Phase 4 – Entwicklungswerkzeuge (1 Woche)
Morph-Regler (4.3), Ghost-Modus (4.4), A/B-Split (4.5), Bump-Chart (4.6),
Story-Kapitel (4.7) als Datendatei.

### Phase 5 – Politur (3–4 Tage)
Bloom/Kantenlicht, Spiegel, Label-Tuning, Kamera-Fahrten, i18n (DE/EN),
Performance-Feinschliff, QA-Suite grün.

### Phase 6 – Optionalmodi (nach Bedarf)
MapLibre-Kartenmodus, Globus-Texturmodus (4.2), Tile-Stil (`legacy_tiles`).

---

## 12. Offene Entscheidungen (bitte klären)

- **O1 Renderer:** Three.js als primäre Engine – Zustimmung? (Empfehlung: ja)
- **O2 MapLibre:** optionaler Zweitmodus aus denselben Artefakten – gewünscht
  oder verwerfen? (Empfehlung: erst nach Phase 5 entscheiden)
- **O3 Globus:** Wow-Modus 4.2 wirklich gewünscht? (Empfehlung: nur wenn
  Zeit nach Phase 5)
- **O4 Solver/Keyframe-Dichte:** nach Messung in Phase 1 – Budget für
  Rechenzeit (Stunden vs. Tage) akzeptabel für Jahres-Keyframes?
- **O5 UI-Sprache:** Deutsch, Englisch oder i18n von Anfang an?
  (Empfehlung: i18n-Strings ab Phase 3, Start Deutsch)
- **O6 Hosting:** statisches Hosting (GitHub Pages/Netlify) genügt –
  kein Server nötig, da alles vorberechnet. Zustimmung?

---

## 13. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Solver zu langsam für 201 Jahres-Keyframes | Messung Phase 1; Fallback 5-Jahres-Raster + Interpolation; cartogram-cpp |
| OTHER_WORLD-Geometrie topologisch schwierig (Löcher, Inseln) | als separate, unkritische Region (flat, keine Höhe); Flächen-Gate nur für Daten-Entitäten |
| Vertexzahl zu hoch für Mobile | Quantisierung + Vereinfachungsgrad konfigurierbar; Mobile-Profil mit Dekaden-Gerüst |
| Daten-Curiosa (Kanada 1820) irritieren | Fußnote/Doku im Menü; keine Datenkorrektur |
| GPU-Morph-Artefakte bei starken Sprüngen (Weltkriege) | Easing + Prüfung „Sprungweite“ im Gate 6.3; ggf. Zwischen-Keyframe |
| Feature-Creep (zu viele Modi) | Kern: 4.1 + Timeline + Panel; alles andere hinter Menü/Feature-Flags |
