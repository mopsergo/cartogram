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
Stabilität der exportierten Keyframes (keine Sprünge zwischen Jahren)
prüfen: `verify-stability`.

## Renderer starten (Web-App)

Voraussetzung: einmalig exportierte Artefakte in `web/public/cartogram/`
(siehe [cartogram-pipeline/PIPELINE.md](cartogram-pipeline/PIPELINE.md),
Abschnitt 3 – ohne Export startet die App mit Ladefehler).

**Schnellstart (Dev-Server):**

```bash
cd ultragram/web
npm install                 # nur beim ersten Mal nötig
npm run dev                 # → http://127.0.0.1:5175
```

**Produktions-Build (empfohlen, lädt deutlich schneller):**

```bash
cd ultragram/web
npm run build               # Bundle nach web/dist/ (kopiert public/ mit)
npm run preview             # → http://localhost:4173
```

Hinweis: der Dev-Server übersetzt TypeScript on-the-fly – der erste
Seitenaufruf kann ~30 s dauern; `preview` bedient das fertige Bundle
und ist nach dem einmaligen `build` sofort da. Nach jedem neuen
`export` der Pipeline: `npm run build` erneut ausführen (oder beim
Dev-Server einfach neu laden, der nimmt die Artefakte direkt aus
`public/`).

## Bedienung

- **Play/Pause** (Leertaste), Zeitslider 1820–2020, ←/→ Einzelschritte
- **Welt-Verlaufsdiagramm** (links unten): Weltbevölkerung,
  Gesamtenergie und Energie pro Kopf als drei Kurven, linear gegen
  das jeweilige Maximum. Der weiße Strich markiert das aktuelle Jahr,
  die Legende zeigt die absoluten Werte (Mrd, Mtoe, kWh – Pro Kopf
  aus Weltenergie/Weltbevölkerung, 1 Mtoe = 1,163·10¹⁰ kWh, gegen
  den Datensatz validiert). **Klick/ziehen ins Diagramm scrubbt das
  Jahr** wie der Zeitslider. Die Jahresanzeige rundet auf ganze
  Jahre – die Timeline interpoliert dazwischen weiterhin weich.
- **Ansicht**: Flach · 2.5D (Höhe = Energie pro Kopf, umschaltbar auf
  Gesamtenergie/Bevölkerung/Weltanteil, abschaltbar) · **Kartogramm-
  Globus** (dieselbe Verformung wie Flach/2.5D, per exakter inverser
  Equal-Earth-Projektion auf die Kugel zurückgeführt – flächentreu,
  die Kartogramm-Flächenverhältnisse bleiben erhalten). Auch der
  Globus extrudiert: Höhen entlang des Kugelradius mit Seitenwänden,
  dieselben 2.5D-Optionen (Höhe + Höhenkennzahl) gelten dort; Länder-
  grenzen laufen als dünne schwarze, geodätisch unterteilte Linien
  über die Kugeloberfläche. Die Welt ist **nahtfrei über den Meridianen**:
  Die Daten werden nicht (wie üblich) am Antimeridian ±180° geschnitten
  (durch Tschukotka!), sondern bei −168,5° mitten in der Beringsee –
  Länder wie die UdSSR/Russland erscheinen auf dem Globus als eine
  durchgehende Landmasse mit echter Küste, ohne künstliche
  Schnittkanten.
- **Farbskala** (gilt für alle drei Ansichten): beginnt am
  **Datenminimum** statt bei 0 – die Skala verschwendet keinen
  Bereich auf Werte, die nie vorkommen. Standard-Transformation
  **Wurzel**: beim Pro-Kopf-Median (~5,7 Tsd. kWh von max ~104 Tsd.)
  läge die lineare Skala bei ~5 % der Rampe und 68 % aller Werte
  in den untersten 10 % (ununterscheidbar dunkel); mit Wurzel sind
  es 0,3 %. Umschaltbar auf **linear** (proportional) oder
  **logarithmisch**. Die Legende nennt Minimum, Maximum und die
  aktive Transformation.
- **Höhenskala (2.5D + Globus)**: empfindlich – normiert gegen das
  **Maximum des jeweiligen Jahres** (frühe Jahre waren gegen das
  globale Maximum fast flach), drei Transformationen umschaltbar:
  **Wurzel** (Standard – kleine Werte betont), **linear** (propor-
  tional) oder **Quadrat** (Spitzenwerte differenzieren stärker).
  Die Extrusions-Blöcke erscheinen durchgängig in der Farbe ihrer
  Deckfläche; geteilte Grenzen werden epsilon-geschrumpft, damit
  jede Wand verlässlich ihre eigene Entitätsfarbe zeigt.
- **Geometrie** (Taste **G**, jetzt überall inkl. Globus): Kartogramm
  ⇄ unverzerrte Original-Ansicht, weicher 600-ms-Übergang. Farben und
  Höhen folgen weiterhin der Jahres-Timeline – die Original-Karte wird
  so zum Choroplethen-/Prismenvergleich. Die Referenz-Ebene
  **„Original-Ländergrenzen im Hintergrund"** (abschaltbar) zeigt in
  Flach **und 2.5D** die unverzerrten Grenzen als Geister-Referenz –
  in 2.5D als hellgraue Linien auf dem dunklen Boden hinter den
  Extrusionsblöcken; in der Original-Ansicht blendet sie sich
  automatisch aus.
- **Kartogramm-Lauf**: „Aktuell (mit Reparaturen)" ⇄ „Original (Git-
  Commit)" – der Originalzustand bleibt als eigener Export
  (`web/public/cartogram/v0`) erhalten und ist jederzeit umschaltbar
  (eigener Mesh, darum Seitenwechsel mit beibehaltenem Jahr).
- **Kartogramm-Fläche** (nur aktueller Lauf): Bevölkerungsanteil ·
  Gesamtenergie · Energie pro Kopf – drei gelöste Kartogramme über
  derselben Topologie; Wechsel morpht weich zwischen den
  Positions-Sätzen. Entitäten ohne Wert der gewählten Kennzahl
  (z. B. Restliche Welt ohne Energiedaten) behalten näherungsweise
  ihre Fläche (passiv, Dichte 1).
- **Ländernamen der Restlichen Welt**: Klick/Hover auf eines der 97
  Länder zeigt den konkreten Namen (Greenland, Mongolia, Sudan …)
  im Tooltip und Detailpanel – auch ohne eigene Datenwerte.
- **2.5D-Boden**: dunkle Grundfläche unter der gesamten Kartenebene;
  die Extrusionen stehen massiv darauf statt zu schweben.
- **Farbkennzahl**: Energie pro Kopf (Standard) · Gesamtenergie ·
  Bevölkerung · Weltbevölkerungsanteil – **alle Skalen linear**, damit
  die krassen Unterschiede sichtbar bleiben
- **Hover** zeigt Tooltip, **Klick** öffnet das Detailpanel mit Zeitreihe
- Flach: unverzerrte Referenz ein/aus; überall: Kamera zurücksetzen
- Drag = rotieren/verschieben, Mausrad = Zoom, Shift-Drag (2.5D) = Pan

Die Schritt-für-Schritt-Dokumentation der Pipeline liegt in
[`cartogram-pipeline/PIPELINE.md`](cartogram-pipeline/PIPELINE.md).

## Deployment (GitHub Pages)

Der Workflow [`.github/workflows/deploy-web.yml`](../.github/workflows/deploy-web.yml)
baut bei jedem Push auf `main` die Web-App **inklusive der eingecheckten
Kartogramm-Artefakte** und veröffentlicht sie auf GitHub Pages.
Die Pipeline läuft bewusst **nicht** im CI (Solver = ~20–40 min pro
Variante) – neu gelöste Kartogramme werden lokal exportiert
(siehe [PIPELINE.md](cartogram-pipeline/PIPELINE.md)) und mit gepusht.

Einmalige Einrichtung: **Settings → Pages → Source: „GitHub Actions"**.
Danach: `git push` → die App liegt kurz darauf auf
`https://<user>.github.io/<repo>/`. Fehlen beim Push die Artefakte,
bricht der Workflow mit einer klaren Anleitung ab (statt einer
leeren Seite).

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
   einzelne (z. B. Israel 7×-Expansion). `repair.py` ersetzt eigene
   Vertices durch eine starr skalierte Originalform – so, dass die
   Animation stabil bleibt (kein Springen zwischen Flow- und
   Reparaturdarstellung):
   - Anker je Polygon-Teil an der **aktuellen Flow-Position** (nicht am
     geografischen Ursprung): die reparierte Form bleibt dort, wo der
     Flow sie hingelegt hat; mehrteilige Entitäten (OTHER_WORLD)
     driften teilweise mit.
   - **Hysterese**: einmal reparierte Entitäten bleiben repariert
     (`force_repair` wird von Jahr zu Jahr weitergereicht) – pro
     Entität höchstens EIN Moduswechsel statt jährlichem Flackern.
     Vorher flackerte z. B. Argentinien 1820–1832 zwischen Flow- und
     Reparaturdarstellung (Positions- und GrößenSprünge).
   - **Vollstarre Platzierung ohne Teilblends**: Blend-Gewichte wären
     diskrete Zustände, die zwischen Jahren umschalten.
   - **Maßstab f – Reparatur nur, wenn sie besser ist**: Die
     gemischte Fläche (starre eigene Küste + geteilte Grenzvertices
     an Flow-Positionen) ist als Funktion von f nicht monoton; der
     Shoelace-Flächenwert eines selbstüberschneidenden Rings ist
     Müll. Eine jährliche Neusuche ließ das Optimum springen
     (UdSSR: f flippte 1856–1881 zwischen ~0,16 und ~1,19, eigene
     Vertices sprungen 6.700 km pro Jahr).
     - **Erstreparatur mit feiner Sonde** (25 Punkte über
       [0,02, 20]× Startmaßstab): beste valide Platzierung nach
       Flächenfehler. Repariert wird NUR bei <= 25 % Fehler –
       sonst bleibt der ehrliche Flow (Brasilien 1820: einzig
       valides Pocket bei 25× Zielfläche hätte die Entität riesig
       aufgebläht; Italien ab 1825: valides Maximum ~0,5× Ziel).
       Die Ring-Ungültigkeit ist dann eine dokumentierte Warnung
       (wie die interior Folds) – die Fläche, die Daten-Semantik
       des Kartogramms, bleibt ehrlich.
     - **Folgereparaturen LOKAL**: Die Sekante sucht nur im Fenster
       [0,5, 2]× des Vorjahres-f (Becken-Kontinuität) mit
       20-%-Akzeptanzpuffer – das Ergebnis ist stetig in den
       Eingaben, kein Springen zwischen Jahren.
     - **Skip ist sticky mit Re-Armierung**: Eine ohne brauchbare
       Platzung übersprungene Entität wird erst neu entschieden,
       wenn ihr Flow wieder gültig war – rein intern, denn
       dargestellt wird immer der Flow: kein sichtbarer Wechsel,
       kein Flackern.
   - **Einmaliger Moduswechsel**: Der Übergang Flow → starr bei der
     ERSTEN Reparatur ist ein einzelner, dokumentierter Sprung
     (Italien 1825, Niederlande 1864, Israel 2002; `verify-stability`
     führt ihn als Übergang, nicht als Fehler).
   - Folds unter Beteiligung geteilter Grenzvertices sind ohne Zerren
     der Nachbarn nicht reparierbar und werden als Warnung je Jahr im
     Qualitätsbericht geführt; frühe Jahre (bis 1870) haben einen
     erhöhten Falt-Schwellwert (`max_inverted_area_fraction_early`).
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
   Referenz-Ghost-Ebene und den Globus.
10. **OTHER_WORLD mit sichtbaren Ländern**: Die Rest-Welt-Entität hat
    EIN Zielgewicht (Restbevölkerung), aber seit der Nutzeranforderung
    KEIN Dissolve mehr – jedes unbeanspruchte Land bleibt als
    eigener Polygon-Teil im Mesh (geteilte Grenzen werden über die
    Koordinaten-Dedupe verschweißt). Im Kartogramm bleibt „Restliche
    Welt" damit als die tatsächlich vorhandenen Länder erkennbar;
    die Anteile *innerhalb* der Region folgen der geografischen Form
    (Einzelwerte gibt es dafür nicht). Historische Aggregate
    (UdSSR etc.) bleiben verschmolzen: eine Datenentität, eine Form.
11. **Drei Flächen-Varianten**: `data.target_metric` wählt die
    Kartogramm-Grundlage (v1 Bevölkerung, v2 Gesamtenergie, v3 Energie
    pro Kopf). Gleiche Topologie, je Variante eigene `positions.f32` +
    `quality.parquet`; der Renderer morpht weich zwischen den
    Positions-Sätzen. Entitäten ohne Wert der Zielkennzahl sind
    passiv (Dichte 1) – der Solver normiert auf die aktiven Entitäten,
    passive behalten näherungsweise ihre Fläche. Für Jahre ohne jede
    Daten in der Kennzahl bleibt die Karte unverzerrt (ehrlich statt
    erfunden).
12. **Kartogramm-Globus**: Der Globus zeigt dieselbe Verformung wie
    Flach/2.5D – je Vertex wird die kartogrammverzerrte Equal-Earth-
    Position per exakter inverser Projektion (Newton, gegen pyproj
    validiert, Abweichung < 2·10⁻⁵°) auf Länge/Breite zurückgerechnet
    und auf die Kugel gesetzt. Equal Earth ist flächentreu, die
    Kartogramm-Flächen gelten also auch auf der Kugel. Taste G blendet
    weich zur unverzerrten Original-Kugel.
13. **Original-Lauf erhalten**: Der Export aus dem ursprünglichen
    Commit liegt als `web/public/cartogram/v0` vor und ist im Renderer
    über „Kartogramm-Lauf" umschaltbar (eigenes Mesh → Neuaufbau mit
    beibehaltenem Jahr). `manifest.json` führt `target_metric` + Label;
    die App zeigt die Flächengrundlage in Titel und Legende.

## Datengrundlage

`data/raw/country_populationshare_energypercapita.csv` – 72 Länder +
`OTHER_WORLD`, 1820–2020 jährlich. `World_share` summiert sich je Jahr
auf 1,0; Israel ist vor 1950 datenlos (passive Entität). Einheiten:
Personen, Mtoe, kWh/Kopf (vgl. `datasets/prep_data.py` im Repo).
