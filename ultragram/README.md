s# ultragram – Animated Energy Cartogram

Interaktive, zeitabhängige Visualisierung von **Bevölkerung** und
**Energieverbrauch** von 1820 bis 2020 als flaches beziehungsweise
2.5D-extrudiertes Cartogramm (Implementierung von
[`FINAL_IMPLEMENTIERUNGS_PLAN.md`](FINAL_IMPLEMENTIERUNGS_PLAN.md)).

```
Fläche zeigt den Anteil an der Weltbevölkerung.
Farbe zeigt Energieverbrauch pro Kopf.
Höhe zeigt Energieverbrauch pro Kopf (im 2.5D umschaltbar).
Zeit zeigt die Entwicklung von 1820 bis 2020.
```

## Architektur (offline-first, Plan §1)

- **Python** (`cartogram-pipeline/`) bereitet Daten, Geometrien und
  Cartogramm-Keyframes vollständig vor.
- **TypeScript/Three.js** (`web/`) übernimmt Darstellung, Interpolation
  und Interaktion – der Browser führt **keine** Cartogramm-Berechnungen
  aus.

```
cartogram-pipeline/          Python-Pipeline (Plan §5, §6, §9)
├── configs/                 entities / pipeline / solver / visualization
├── data/raw|reference       Faktengrundlage + Natural Earth
├── src/worldcarto/          ingest, geometry, topology, triangulate,
│   └── solvers/              temporal, quality, export, cli
│       ├── cartogram_cpp    Produktionssolver laut Plan (optionale Bindings)
│       ├── carto_flow       Flow-Solver (Gastner-Seguy-More 2018) – hier produktiv
│       └── legacy_tiles     Bassogram-Tile-Prototyp (Makro-Cluster-Port)
├── tests/                   pytest
├── build-cache/             Mesh- und Frame-Caches (hash-versioniert)
└── dist/cartogram/v1/       Export-Artefakte für den Browser

web/                         Renderer (Plan §7)
├── src/
│   ├── data/                Artefakt-Loader (Exportvertrag §6)
│   ├── renderers/           FlatCartogram / ExtrudedCartogram / ReferenceGlobe
│   ├── timeline/            Timeline-State + Playback
│   └── ui/                  Legende, Detailpanel, Steuerung
└── public/cartogram/v1/     Kopie der Export-Artefakte
```

## Pipeline ausführen

```bash
cd cartogram-pipeline
PYTHONPATH=src python3 -m worldcarto.cli validate   # Rohdaten (Plan §2)
PYTHONPATH=src python3 -m worldcarto.cli ingest     # kanonisches Parquet
PYTHONPATH=src python3 -m worldcarto.cli mesh        # kanonisches Mesh + Triangulierung
PYTHONPATH=src python3 -m worldcarto.cli solve       # Jahres-Keyframes (Cache)
PYTHONPATH=src python3 -m worldcarto.cli export      # Artefakte + Kopie nach web/
PYTHONPATH=src python3 -m worldcarto.cli debug-frames --years 1820 1900 1950 2000 2020
```

oder alles auf einmal: `build`. Qualität ansehen: `quality`.

## Renderer starten

```bash
cd web
npm install
npm run dev        # http://127.0.0.1:5175
npm run build      # Produktions-Bundle nach web/dist
```

## Bedienung

- **Play/Pause** (Leertaste), Zeitslider 1820–2020, ←/→ Einzelschritte
- **Ansicht**: Flach · 2.5D (Höhe = Energie pro Kopf, umschaltbar auf
  Gesamtenergie/Bevölkerung/Weltanteil, abschaltbar) · Globus
- **Farbkennzahl**: Energie pro Kopf (Standard) · Gesamtenergie ·
  Bevölkerung · Weltbevölkerungsanteil – **alle Skalen linear**, damit
  die krassen Unterschiede sichtbar bleiben
- **Hover** zeigt Tooltip, **Klick** öffnet das Detailpanel mit Zeitreihe
- Flach: unverzerrte Referenz ein/aus; überall: Kamera zurücksetzen
- Drag = rotieren/verschieben, Mausrad = Zoom, Shift-Drag (2.5D) = Pan

## Umgesetzte Entscheidungen und Abweichungen (dokumentiert)

1. **Solver**: `cartogram_cpp` ist laut Plan Produktionssolver, hat aber
   für Python 3.13 keine installierbaren Bindings (`flowbasedcartograms`
   hat kein Rad). Die Kette `solver.yaml` fällt daher auf **carto_flow**
   zurück – eine Weiterentwicklung des im Repo bewährten
   mopsogram-Prototyps für die Equal-Earth-Ebene und das kanonische Mesh
   (Gastner, Seguy & More, PNAS 2018). Der Wrapper bleibt vorhanden und
   greift, sobald Bindings verfügbar sind.
2. **Projektion**: Equal Earth (EPSG:8857), flächentreu (Plan §5.3).
   Natural Earth 110m ist bereits generalisiert und teilt Grenzvertices
   exakt zwischen Nachbarn – eine zusätzliche Vereinfachung ist
   standardmäßig deaktiviert, damit gemeinsame Grenzen erhalten bleiben.
3. **Keine jährliche Neutriangulierung**: kanonisches Mesh mit festen
   Vertex-IDs, Ringen und Dreiecken (Plan §5.5); Earcut ohne
   Steiner-Punkte.
4. **Interior Dreieckslappen (Folds)**: Starke Verformungen (Kanada 1820
   ~150×-Kontraktion, UdSSR 3,7×) falten interior Dreieckslappen auch mit
   Referenz-Solvern. Die Qualitätsprüfung bewertet deshalb die *gefaltete
   Fläche* gegen einen Schwellwert (`max_inverted_area_fraction`) und
   prüft Polygon-Validität als harte Größe; der Renderer zeichnet
   DoubleSide + Grenzlinien, sodass Lappen visuell irrelevant sind
   (`quality.py`, `solver.yaml`).
5. **Ring-Selbstüberschneidungen**: Bei extremer Verformung verbleiben
   einzelne (z. B. Israel 7×-Expansion). `repair.py` blendet eigene
   Vertices zur Originalform zurück; Folds unter Beteiligung geteilter
   Grenzvertices sind ohne Zerren der Nachbarn nicht reparierbar und
   werden als Warnung je Jahr im Qualitätsbericht geführt.
6. **Mindestzielfläche** (`min_target_share`, Water-Filling): Anteile
   unter 0,02 % der Weltbevölkerung (z. B. Panama 1820 = 128 km²
   Zielfläche, kleiner als eine Gitterzelle) sind mit dem 110m-Mesh
   nicht darstellbar; aufgestockte Entitäten werden renormiert (Summe
   bleibt 1) und im Qualitätsbericht markiert.
7. **legacy_tiles**: Port des Bassogram-Tile-Prototyps auf Makrocluster
   (Largest-Remainder, Kraftmodell, Overlapprojektion, Warm-Start). Die
   Länderebene des Prototyps (Tile-Partition *innerhalb* eines Clusters)
   ist auf dem gemeinsamen Mesh nicht darstellbar; der Modus ist für
   Vergleiche/Regressionen, nicht produktioniv.
8. **Warm-Start-Kandidaten**: Die Maschinerie (Direct + Warm-Start,
  Validierung, Auswahl des Besten) ist implementiert und getestet;
   standardmäßig ist `warm_start: false`, da Direct-Solves bei jährlichen
   Zielen zeitlich kohärent sind.
9. **Erweiterungen des Exportvertrags**: `positions_original.f32` und
   `vertices_lonlat.f32` sind dokumentierte Zusatzartefakte für die
   Referenz-Ghost-Ebene und den Reference Globe.

## Datengrundlage

`data/raw/country_populationshare_energypercapita.csv` – 72 Länder +
`OTHER_WORLD`, 1820–2020 jährlich. `World_share` summiert sich je Jahr
auf 1,0; Israel ist vor 1950 datenlos (passive Entität). Einheiten:
Personen, Mtoe, kWh/Kopf (vgl. `datasets/prep_data.py` im Repo).
