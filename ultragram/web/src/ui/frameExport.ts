/**
 * PNG-Einzelbildexport für Animationen (16:9).
 *
 * Die 16:9-Vorschau beschränkt die Canvas auf den Exportausschnitt;
 * Zoom und Perspektive werden dort eingestellt und unverändert in
 * der gewählten Auflösung gerendert. Ziel ist ein vom Nutzer gewählter
 * Ordner (File System Access API, Chromium); ohne diese API sammelt
 * der Export die Bilder im Speicher und bietet sie danach als ZIP zum
 * Herunterladen an (ab ZIP_PART_LIMIT in mehreren Teilen).
 */
import type { App } from "../app";
import { ZipBuilder, ZIP_PART_LIMIT } from "./zip";

const ASPECT = 16 / 9;
/** Einträge je ZIP (Zähler im Archivende sind 16 Bit) */
const ZIP_MAX_ENTRIES = 65000;

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
  const downloads = document.getElementById("exportDownloads")!;
  let downloadUrls: string[] = [];

  const clearDownloads = () => {
    for (const url of downloadUrls) URL.revokeObjectURL(url);
    downloadUrls = [];
    downloads.replaceChildren();
  };
  const offerDownload = (blob: Blob, name: string, frames: number) => {
    const url = URL.createObjectURL(blob);
    downloadUrls.push(url);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.className = "export-download";
    a.textContent = `${name} herunterladen (${frames} Bilder, `
      + `${(blob.size / 1024 ** 2).toFixed(0)} MB)`;
    downloads.append(a);
  };

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
    let finishZip: (() => void) | null = null;
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
      // Bilder sammeln, am Ende als ZIP anbieten (ein Download statt
      // Hunderter Einzel-Downloads)
      clearDownloads();
      const base = `cartogram_${yearFrom}-${yearTo}_${width}x${height}`;
      const done: { blob: Blob; frames: number }[] = [];
      let zip = new ZipBuilder();
      const closePart = () => {
        if (zip.count > 0) done.push({ blob: zip.finish(), frames: zip.count });
        zip = new ZipBuilder();
      };
      write = async (name, png) => {
        if (zip.count >= ZIP_MAX_ENTRIES
            || zip.size + png.size > ZIP_PART_LIMIT) closePart();
        await zip.add(name, png);
      };
      finishZip = () => {
        closePart();
        done.forEach((d, i) => offerDownload(d.blob,
          done.length > 1 ? `${base}_teil${i + 1}.zip` : `${base}.zip`,
          d.frames));
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
      if (finishZip) {
        status.textContent += " – ZIP bereit:";
        finishZip();
      }
    } catch (err) {
      console.error("[export]", err);
      status.textContent = `Fehler: ${String(err)}`;
      // bereits gerenderte Bilder nicht verwerfen
      finishZip?.();
    } finally {
      running = false;
      button.textContent = "PNG-Frames exportieren";
    }
  });
}
