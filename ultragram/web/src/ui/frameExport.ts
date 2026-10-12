/**
 * PNG-Einzelbildexport für Animationen (16:9).
 *
 * Die 16:9-Vorschau beschränkt die Canvas auf den Exportausschnitt;
 * Zoom und Perspektive werden dort eingestellt und unverändert in
 * der gewählten Auflösung gerendert. Ziel ist ein vom Nutzer gewählter
 * Ordner (File System Access API, Chromium); ohne diese API lädt der
 * Browser die Bilder einzeln herunter.
 */
import type { App } from "../app";

const ASPECT = 16 / 9;

type DirHandle = {
  getFileHandle(name: string, opts: { create: boolean }): Promise<{
    createWritable(): Promise<{
      write(data: Blob): Promise<void>;
      close(): Promise<void>;
    }>;
  }>;
};
type DirPicker = (opts?: { mode?: "readwrite"; id?: string }) =>
  Promise<DirHandle>;

export function wireFrameExport(app: App, yearMin: number,
                                yearMax: number): void {
  const preview = document.getElementById("exportPreview") as
    HTMLInputElement;
  const resSelect = document.getElementById("exportRes") as
    HTMLSelectElement;
  const fromInput = document.getElementById("exportFrom") as
    HTMLInputElement;
  const toInput = document.getElementById("exportTo") as HTMLInputElement;
  const fpyInput = document.getElementById("exportFpy") as HTMLInputElement;
  const labelToggle = document.getElementById("exportYearLabel") as
    HTMLInputElement;
  const legendToggle = document.getElementById("exportLegend") as
    HTMLInputElement;
  const chartToggle = document.getElementById("exportWorldChart") as
    HTMLInputElement;
  const button = document.getElementById("exportBtn") as HTMLButtonElement;
  const status = document.getElementById("exportStatus")!;

  fromInput.min = toInput.min = String(yearMin);
  fromInput.max = toInput.max = String(yearMax);
  fromInput.value = String(yearMin);
  toInput.value = String(yearMax);

  const updateSummary = () => {
    const from = Number(fromInput.value), to = Number(toInput.value);
    const fpy = Number(fpyInput.value);
    if (!(to >= from) || !(fpy >= 1)) {
      status.textContent = "Ungültiger Bereich";
      return;
    }
    const n = Math.round((to - from) * fpy) + 1;
    status.textContent = `${n} Bilder · bei 25 fps ${(n / 25).toFixed(1)} s`;
  };
  for (const el of [fromInput, toInput, fpyInput]) {
    el.addEventListener("input", updateSummary);
  }
  updateSummary();

  preview.addEventListener("change", () => {
    app.setPreviewAspect(preview.checked ? ASPECT : null);
  });

  let running = false;
  let cancel = false;

  button.addEventListener("click", async () => {
    if (running) {
      cancel = true;
      button.textContent = "Wird abgebrochen …";
      return;
    }
    const yearFrom = Math.max(yearMin, Math.min(yearMax,
      Math.round(Number(fromInput.value))));
    const yearTo = Math.max(yearFrom, Math.min(yearMax,
      Math.round(Number(toInput.value))));
    const framesPerYear = Math.max(1, Math.round(Number(fpyInput.value)));
    const [width, height] = resSelect.value.split("x").map(Number);

    // Ziel wählen, bevor gerendert wird (Benutzergeste nötig)
    let write: (name: string, png: Blob) => Promise<void>;
    const picker = (window as unknown as { showDirectoryPicker?: DirPicker })
      .showDirectoryPicker;
    if (picker) {
      let dir: DirHandle;
      try {
        dir = await picker({ mode: "readwrite", id: "cartogram-frames" });
      } catch {
        return;   // Auswahl abgebrochen
      }
      write = async (name, png) => {
        const file = await dir.getFileHandle(name, { create: true });
        const w = await file.createWritable();
        await w.write(png);
        await w.close();
      };
    } else {
      write = async (name, png) => {
        const url = URL.createObjectURL(png);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        a.click();
        // Kurze Pause: Browser drosseln sonst Mehrfach-Downloads
        await new Promise((r) => setTimeout(r, 150));
        URL.revokeObjectURL(url);
      };
    }

    running = true;
    cancel = false;
    button.textContent = "Abbrechen";
    const started = performance.now();
    try {
      const done = await app.exportFrames({
        width, height, yearFrom, yearTo, framesPerYear,
        yearLabel: labelToggle.checked,
        legend: legendToggle.checked,
        worldChart: chartToggle.checked,
        write,
        progress: (d, total) => {
          status.textContent = `Bild ${d} / ${total}`;
        },
        cancelled: () => cancel,
      });
      const secs = ((performance.now() - started) / 1000).toFixed(0);
      status.textContent = cancel
        ? `Abgebrochen nach ${done} Bildern`
        : `Fertig: ${done} Bilder in ${secs} s`;
    } catch (err) {
      console.error("[export]", err);
      status.textContent = `Fehler: ${String(err)}`;
    } finally {
      running = false;
      button.textContent = "PNG-Frames exportieren";
    }
  });
}
