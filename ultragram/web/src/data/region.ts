/** Bezugsgebiet der Anteile und Summen: ganze Welt oder – in
 *  Regions-Läufen (manifest.region, z. B. Europa) – die Region.
 *  Bevölkerungsanteil, Summen-Diagramm und Beschriftungen beziehen
 *  sich dann auf die Region; gesetzt einmal beim App-Start. */
let regionLabel: string | null = null;

export function setRegion(label: string | null): void {
  regionLabel = label;
}

/** „Anteil an der Weltbevölkerung" bzw. „… Bevölkerung (Europa)" */
export function shareLabel(): string {
  return regionLabel
    ? `Anteil an der Bevölkerung (${regionLabel})`
    : "Anteil an der Weltbevölkerung";
}

/** Kurzform für Auswahllisten */
export function shareShort(): string {
  return regionLabel
    ? `Anteil Bevölkerung (${regionLabel})`
    : "Anteil Weltbevölkerung";
}

/** Nachsatz für Prozentwerte: „12 % der Weltbevölkerung" */
export function shareSuffix(): string {
  return regionLabel
    ? `der Bevölkerung (${regionLabel})`
    : "der Weltbevölkerung";
}

/** Titel des Summen-Diagramms: „Welt gesamt" / „Europa gesamt" */
export function totalLabel(): string {
  return `${regionLabel ?? "Welt"} gesamt`;
}

/** Zeilenbeschriftung im Detailpanel: „Weltanteil" / „Anteil (Europa)" */
export function shareTiny(): string {
  return regionLabel ? `Anteil (${regionLabel})` : "Weltanteil";
}
