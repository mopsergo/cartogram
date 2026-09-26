// Final-QA mit vollem Zeitraum 1820–2020 (201 Frames).
export default async function run(page, ui) {
  await page.waitForSelector("#app canvas", { timeout: 60000 });
  // Warten bis die App tatsächlich lebt (Jahresanzeige rendert)
  await page.waitForFunction(() => {
    const el = document.getElementById("yearDisplay");
    return el && el.textContent.length > 0 &&
      !document.getElementById("bootStatus");
  }, { timeout: 60000 });
  await page.waitForTimeout(1000);
  const out = {};

  // --- Manifest-Check: 201 Frames -------------------------------
  out.manifest = await page.evaluate(async () => {
    const m = await fetch("cartogram/v1/manifest.json").then(r => r.json());
    return {
      frames: m.years.frames.length,
      range: m.years.data_range,
      entities: m.dimensions.num_entities,
      triangles: m.dimensions.num_triangles,
      solver: m.solver.chain,
    };
  });

  // --- Jahresgrenzen --------------------------------------------
  // App startet mit Autoplay (außer bei prefers-reduced-motion):
  // nur klicken, wenn die Zeit stehen bleibt.
  const yearBefore = await page.evaluate(
    () => document.getElementById("yearDisplay").textContent);
  await page.waitForTimeout(800);
  let yearNow = await page.evaluate(
    () => document.getElementById("yearDisplay").textContent);
  if (yearNow === yearBefore) {
    await page.click("#playBtn");
    await page.waitForTimeout(800);
    yearNow = await page.evaluate(
      () => document.getElementById("yearDisplay").textContent);
  }
  out.playback = { yearBefore, yearNow,
    running: yearNow !== yearBefore };
  await page.selectOption("#speedSelect", "20");
  await page.waitForFunction(
    () => document.getElementById("yearDisplay").textContent === "2020",
    { timeout: 60000 });
  out.endYear = await page.evaluate(
    () => document.getElementById("yearDisplay").textContent);

  // --- Ansichten bei 2020 ---------------------------------------
  const views = {};
  for (const mode of ["flat", "extruded", "globe"]) {
    await page.click(`#viewBtns button[data-mode="${mode}"]`);
    await page.waitForTimeout(1000);
    views[mode] = await page.evaluate(() => {
      const canvas = document.querySelector("#app canvas");
      const c2 = document.createElement("canvas");
      c2.width = canvas.width; c2.height = canvas.height;
      const ctx = c2.getContext("2d");
      ctx.drawImage(canvas, 0, 0);
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let colored = 0, total = 0;
      const colors = new Set();
      for (let y = 0; y < canvas.height; y += 6) {
        for (let x = 0; x < canvas.width; x += 6) {
          const i = (y * canvas.width + x) * 4;
          total++;
          const r = img[i], g = img[i + 1], b = img[i + 2];
          if (Math.max(r, g, b) - Math.min(r, g, b) > 18) {
            colored++;
            colors.add(`${r >> 5},${g >> 5},${b >> 5}`);
          }
        }
      }
      return {
        colored: +(colored / total).toFixed(3),
        distinctColorBuckets: colors.size,
      };
    });
  }
  out.viewsAt2020 = views;

  // --- Kennzahl-Umschalter ---------------------------------------
  await page.click(`#viewBtns button[data-mode="flat"]`);
  await page.waitForTimeout(500);
  const metrics = {};
  for (const value of ["3", "2", "0", "1"]) {
    await page.selectOption("#metricSelect", value);
    await page.dispatchEvent("#metricSelect", "change");
    await page.waitForTimeout(400);
    metrics[value] = await page.evaluate(() => {
      const canvas = document.querySelector("#app canvas");
      const c2 = document.createElement("canvas");
      c2.width = canvas.width; c2.height = canvas.height;
      const ctx = c2.getContext("2d");
      ctx.drawImage(canvas, 0, 0);
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const colors = new Set();
      for (let y = 0; y < canvas.height; y += 6) {
        for (let x = 0; x < canvas.width; x += 6) {
          const i = (y * canvas.width + x) * 4;
          if (Math.max(img[i], img[i+1], img[i+2]) -
              Math.min(img[i], img[i+1], img[i+2]) > 18) {
            colors.add(`${img[i] >> 5},${img[i+1] >> 5},${img[i+2] >> 5}`);
          }
        }
      }
      return colors.size;
    });
  }
  out.distinctColorsByMetric = metrics;

  // --- Detailpanel China bei 2020 ---------------------------------
  await page.click("#resetCam");
  await page.waitForTimeout(400);
  // China ist 2020 riesig – Klick oberhalb der Mitte
  const size = await page.evaluate(() => ({
    w: window.innerWidth, h: window.innerHeight }));
  await page.mouse.click(size.w * 0.72, size.h * 0.42);
  await page.waitForTimeout(500);
  out.detail = {
    visible: await page.evaluate(() =>
      document.getElementById("detail").classList.contains("show")),
    name: await page.evaluate(() =>
      document.getElementById("detailName").textContent),
    rows: await page.evaluate(() =>
      document.getElementById("detailRows").innerText.replace(/\n/g, " | ")),
  };

  // --- Legende -----------------------------------------------------
  out.legend = await page.evaluate(() => ({
    min: document.getElementById("legendMin").textContent,
    max: document.getElementById("legendMax").textContent,
    caption: document.getElementById("legendCaption").textContent,
  }));

  return out;
}
