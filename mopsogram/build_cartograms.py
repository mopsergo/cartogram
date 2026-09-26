"""
Berechnet die Kartogramm-Snapshots (Flaeche ~ Bevoelkerung) vorab:

    python build_cartograms.py

Erzeugt/ergaenzt cartogram_cache.json mit einem Snapshot je 10 Jahre
(1820, 1830, ..., 2020). Die App laedt die Snapshots dann sofort; ohne
diesen Schritt berechnet sie fehlende Jahre beim ersten Start selbst
(dauert ~6 s pro Dekade).
"""
from meshdata import build

if __name__ == "__main__":
    import time

    import cartogram

    _, _, store, _ = build(year0=1820, mode="sqrt")
    years = list(range(1820, 2021, 10))
    t0 = time.time()
    cartogram.snapshots(store, years)
    print(f"Fertig: {len(years)} Snapshots in "
          f"{(time.time() - t0) / 60:.1f} min -> cartogram_cache.json")
