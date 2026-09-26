/** Einstiegspunkt: Artefakte laden, App starten, Fehler anzeigen. */
import { loadArtifacts } from "./data/artifacts";
import { App } from "./app";

async function main(): Promise<void> {
  const status = document.createElement("div");
  status.id = "bootStatus";
  status.style.cssText =
    "position:absolute; inset:0; display:flex; align-items:center;" +
    "justify-content:center; color:#8b98a9; font-size:15px;" +
    "z-index:5; pointer-events:none;";
  status.textContent = "Lade Cartogramm-Artefakte …";
  document.getElementById("app")!.appendChild(status);

  try {
    const art = await loadArtifacts();
    console.log("[app] Artefakte geladen, starte App …");
    status.remove();
    (window as unknown as { __app: App }).__app =
      new App(art, document.getElementById("app")!);
    console.log("[app] App bereit");
  } catch (err) {
    status.style.color = "#ff8fa3";
    status.style.whiteSpace = "pre-wrap";
    status.textContent =
      "Fehler beim Laden der Artefakte:\n" + String(err) +
      "\n\nBitte zuerst die Pipeline ausführen:\n" +
      "  cd cartogram-pipeline && PYTHONPATH=src python3 -m worldcarto.cli export";
    console.error(err);
  }
}

void main();
