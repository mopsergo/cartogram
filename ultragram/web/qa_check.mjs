// QA: Rendert die App korrekt? Pixel-Statistik + Interaktionstest.
// node browser.mjs http://127.0.0.1:5175/ --script qa_check.mjs
export default async function run(page, ui) {
  const out = {};
  await page.waitForSelector("canvas", { timeout: 15000 });
  await page.waitForTimeout(2500); // Ersts-Frame + Autoplay

  // --- Pixelstatistik des WebGL-Canvas -----------------------------
  out.pixels = await page.evaluate(() => {
    const canvas = document.querySelector("#app canvas");
    if (!canvas) return { error: "kein Canvas" };
    const w = canvas.width, h = canvas.height;
    const c2 = document.createElement("canvas");
    c2.width = w; c2.height = h;
    const ctx = c2.getContext("2d");
    ctx.drawImage(canvas, 0, 0);
    const img = ctx.getImageData(0, 0, w, h).data;
    let bg = 0, colored = 0, grey = 0;
    const colors = new Set();
    for (let y = 0; y < h; y += 4) {
      for (let x = 0; x < w; x += 4) {
        const i = (y * w + x) * 4;
        const r = img[i], g = img[i + 1], b = img[i + 2];
        if (Math.abs(r - 13) < 6 && Math.abs(g - 17) < 6 &&
            Math.abs(b - 23) < 6) { bg++; continue; }
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
        if (mx - mn < 18) { grey++; continue; }
        colored++;
        colors.add(`${r >> 4},${g >> 4},${b >> 4}`);
      }
    }
    return {
      size: [w, h],
      bgFraction: +(bg / (bg + colored + grey)).toFixed(3),
      coloredFraction: +(colored / (bg + colored + grey)).toFixed(3),
      greyFraction: +(grey / (bg + colored + grey)).toFixed(3),
      distinctColors: colors.size,
    };
  });

  // --- Jahresanzeige + Autoplay -----------------------------------
  out.year1 = await page.evaluate(
    () => document.getElementById("yearDisplay").textContent);
  await page.waitForTimeout(1500);
  out.year2 = await page.evaluate(
    () => document.getElementById("yearDisplay").textContent);
  out.playing = out.year1 !== out.year2;

  // --- Pause + Slider --------------------------------------------
  await page.click("#playBtn");
  await page.waitForTimeout(300);
  await page.fill("#yearSlider", "1843");
  await page.dispatchEvent("#yearSlider", "input");
  await page.waitForTimeout(600);
  out.yearAfterScrub = await page.evaluate(
    () => document.getElementById("yearDisplay").textContent);

  // --- Ansichten umschalten ---------------------------------------
  const views = {};
  for (const mode of ["flat", "extruded", "globe"]) {
    await page.click(`#viewBtns button[data-mode="${mode}"]`);
    await page.waitForTimeout(700);
    views[mode] = await page.evaluate(() => {
      const canvas = document.querySelector("#app canvas");
      const c2 = document.createElement("canvas");
      c2.width = canvas.width; c2.height = canvas.height;
      const ctx = c2.getContext("2d");
      ctx.drawImage(canvas, 0, 0);
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let colored = 0, total = 0;
      for (let y = 0; y < canvas.height; y += 6) {
        for (let x = 0; x < canvas.width; x += 6) {
          const i = (y * canvas.width + x) * 4;
          total++;
          const r = img[i], g = img[i + 1], b = img[i + 2];
          if (Math.max(r, g, b) - Math.min(r, g, b) > 18) colored++;
        }
      }
      return +(colored / total).toFixed(3);
    });
  }
  out.coloredByView = views;

  // --- Klick in die Kartenmitte -> Detailpanel --------------------
  await page.click(`#viewBtns button[data-mode="flat"]`);
  await page.click("#resetCam");
  await page.waitForTimeout(400);
  const size = await page.evaluate(() => ({
    w: window.innerWidth, h: window.innerHeight }));
  await page.mouse.click(size.w / 2, size.h / 2);
  await page.waitForTimeout(400);
  out.detailVisible = await page.evaluate(() =>
    document.getElementById("detail").classList.contains("show"));
  out.detailName = await page.evaluate(() =>
    document.getElementById("detailName").textContent);

  // --- Tooltip bei Hover ------------------------------------------
  await page.mouse.move(size.w * 0.4, size.h * 0.45);
  await page.waitForTimeout(250);
  out.tooltipShown = await page.evaluate(() =>
    getComputedStyle(document.getElementById("tooltip")).display !== "none");
  out.tooltipText = await page.evaluate(() =>
    document.getElementById("tooltip").textContent);

  return out;
}
