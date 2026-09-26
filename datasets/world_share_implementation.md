# World Share, Weltbevölkerung und OTHER_WORLD

## Ziel

Dieses Dokument beschreibt die korrekte Berechnung der jährlichen Weltbevölkerungsanteile (`world_share`) für das Cartogram-Projekt.

---

## Zentrale Erkenntnis

Vor der Erzeugung der Cartogramme muss für jedes Jahr die tatsächliche Weltbevölkerung bekannt sein.

Die Bevölkerungszahlen der betrachteten Länder allein reichen nicht aus.

Für jedes Jahr wird benötigt:

```python
world_population[year]
```

Empfohlene Quelle:

- WEC Table P.1 (primär)
- alternativ OWID / Gapminder / UN WPP als Cross-Check

Da die WEC-Länderdaten aus derselben Methodik stammen, sollte standardmäßig die WEC-Weltbevölkerung verwendet werden.

die tatsächliche weltbevölkerung kann aus [Table_A1P1_energy_population_percapita.csv](Table_A1P1_energy_population_percapita.csv) übernommen werden.

---

## Berechnung von world_share

Für jedes Land und Jahr:

```python
world_share = (
    country_population
    / world_population
)
```

Beispiel:

```python
country_population = 43.851  # Mio.
world_population = 7795.482  # Mio.

world_share = 43.851 / 7795.482
```

Ergebnis:

```text
0.5625 %
```

---

## Warum Popu_share nicht genügt

Die vorhandene Spalte `Population_share` basiert auf der Summe der im Datensatz enthaltenen Länder.

Formal:

```python
sample_share = (
    country_population
    / represented_population
)
```

Nicht enthaltene Weltregionen fehlen dabei vollständig.

Dadurch entsteht keine echte Weltquote.

---

## Berechnung der fehlenden Bevölkerung

Für jedes Jahr:

```python
represented_population = sum(country_population)

remainder_population = (
    world_population
    - represented_population
)
```

---

## OTHER_WORLD

Der fehlende Anteil wird als zusätzliche Entität modelliert.

```python
OTHER_WORLD = remainder_population
```

Dadurch erhält der Cartogram-Solver die vollständige Weltbevölkerung.

---

## Berechnung der Anteile

### Länder

```python
country_share = (
    country_population
    / world_population
)
```

### OTHER_WORLD

```python
other_world_share = (
    remainder_population
    / world_population
)
```

### Validierung

```python
sum(country_share) + other_world_share
≈ 1.0
```

---

## Warum OTHER_WORLD notwendig ist

Cartogram-Solver normalisieren alle übergebenen Gewichte auf 100 %.

Wenn nur die betrachteten Länder übergeben werden:

```python
country_population
/ represented_population
```

entsteht automatisch wieder die Stichprobenquote.

Die fehlenden Weltregionen würden mathematisch verschwinden.

Daher muss `OTHER_WORLD` als echte geometrische Region vorhanden sein.

---

## Geometrische Umsetzung

### Eingang

- vollständige Weltgeometrie
- WEC-Ländergeometrien

### Berechnung

```python
OTHER_WORLD = (
    WORLD_GEOMETRY
    - REPRESENTED_GEOMETRIES
)
```

Anschließend:

```python
72 WEC Entities
+ OTHER_WORLD
```

werden gemeinsam an den Solver übergeben.

---

## Pipeline-Reihenfolge

### Phase 1

Weltbevölkerung laden.

```python
world_population[1820]
...
world_population[2020]
```

### Phase 2

world_share berechnen.

### Phase 3

OTHER_WORLD berechnen.

### Phase 4

Zielgewichte exportieren.

### Phase 5

Cartogram-Solver ausführen.

---

## Zu exportierende Felder

```python
country_id
year
population
world_population
world_share
```

Zusätzlich:

```python
entity_id='OTHER_WORLD'
year
population
world_population
world_share
```

---

## Empfehlung

Der wissenschaftlich korrekte Standardmodus ist:

```text
world_share + OTHER_WORLD
```

Nicht:

```text
Popu_share
```

Erst nachdem für jedes Jahr die korrekte Weltbevölkerung vorliegt, sollten die Zielgewichte für den Cartogram-Solver erzeugt werden. Andernfalls wird die Stichprobe erneut auf 100 % normiert und die tatsächliche globale Verteilung geht verloren.
