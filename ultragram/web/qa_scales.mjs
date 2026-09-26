// QA der drei Nutzer-Anforderungen:
// 1. Globus zeigt Zeitänderung (Farben 1820 vs. 2020 deutlich verschieden)
// 2. Lineare Skalen (viele unterscheidbare Farben)
// 3. Höhenkennzahl im 2.5D umschaltbar
export default async function run(page, ui) {
  await page.waitForSelector("#app canvas", { timeout: 60000 });
  await page.waitForFunction(() => !document.getElementById("bootStatus"),
    { timeout: 60000 });
  await page.waitForTimeout(800);
  const out = {};

  const sampleCanvas = () => page.evaluate(() => {
    const canvas = document.querySelector("#app canvas");
    const c2 = document.createElement("canvas");
    c2.width = canvas.width; c2.height = canvas.height;
    const ctx = c2.getContext("2d");
    ctx.drawImage(canvas, 0, 0);
    const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    // Stichproben-Raster + Farbbuckets + mittlere Helligkeit
    let lum = 0, n = 0;
    const buckets = new Set();
    for (let y = 0; y < canvas.height; y += 5) {
      for (let x = 0; x < canvas.width; x += 5) {
        const i = (y * canvas.width + x) * 4;
        const r = img[i], g = img[i + 1], b = img[i + 2];
        lum += (r + g + b) / 3; n++;
        buckets.add(`${r >> 4},${g >> 4},${b >> 4}`);
      }
    }
    return { buckets: buckets.size, avgLum: Math.round(lum / n) };
  });

  const seek = async (year) => {
    await page.click("#playBtn"); // ggf. Pause
    await page.fill("#yearSlider", String(year));
    await page.dispatchEvent("#yearSlider", "input");
    await page.waitForTimeout(700);
  };

  // --- 1: Globus-Zeitänderung --------------------------------------
  await page.click('#viewBtns button[data-mode="globe"]');
  await page.waitForTimeout(600);
  await seek(1820);
  const g1820 = await sampleCanvas();
  await seek(2020);
  const g2020 = await sampleCanvas();
  out.globeTimeChange = {
    jahr1820: g1820, jahr2020: g2020,
    farbenAenderung: Math.abs(g1820.avgLum - g2020.avgLum),
  };

  // --- 2: Lineare Skalen in der Flachansicht ------------------------
  await page.click('#viewBtns button[data-mode="flat"]');
  await page.waitForTimeout(600);
  await seek(1820);
  const f1820 = await sampleCanvas();
  await seek(2020);
  const f2020 = await sampleCanvas();
  out.flatLinear = { jahr1820: f1820, jahr2020: f2020 };

  // --- 3: Höhenkennzahl umschaltbar --------------------------------
  await page.click('#viewBtns button[data-mode="extruded"]');
  await page.waitForTimeout(600);
  await seek(2020);
  // Kameraposition fixieren: Zoom weit weg für vergleichbare Fläche
  const h1 = await sampleCanvas();
  await page.selectOption("#heightSelect", "2"); // Gesamtenergie
  await page.dispatchEvent("#heightSelect", "change");
  await page.waitForTimeout(700);
  const h2 = await sampleCanvas();
  await page.selectOption("#heightSelect", "3"); // zurück: pro Kopf
  await page.dispatchEvent("#heightSelect", "change");
  await page.waitForTimeout(700);
  const h3 = await sampleCanvas();
  out.heightSwitch = {
    proKopf: h1, gesamtenergie: h2, zurueck: h3,
    aenderung: Math.abs(h1.avgLum - h2.avgLum),
  };

  // --- Legende zeigt linear -----------------------------------------
  out.legend = await page.evaluate(() => ({
    caption: document.getElementById("legendCaption").textContent,
    min: document.getElementById("legendMin").textContent,
    max: document.getElementById("legendMax").textContent,
  }));
  return out;
}
