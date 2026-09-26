/* QA End-to-End: laeuft Autoplay, reagiert die KARTE (Pixel!) auf Drag/Wheel?
 * Beweiskette:
 *  1. nach Load: playBtn = "❚❚"  (App startet spielend)
 *  2. nach 2,2 s: Jahr > 1820     (Autoplay-Tick funktioniert)
 *  3. Klick Play -> Pause, Screenshot A (nur Karte)
 *  4. Drag auf ~92 % -> Screenshot B, Pixel-Diff A/B  (Restyle wirkt)
 *  5. Mausrad 5x -> +5 Jahre
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 150000 }
  );
  await page.waitForTimeout(300);

  const read = () =>
    page.evaluate(() => ({
      year: document.getElementById("year-label").textContent,
      total: document.getElementById("total-label").textContent,
      playBtn: document.getElementById("play-btn").textContent,
      thumbNow: (document.querySelector(".dash-slider-thumb") || {})
        .getAttribute("aria-valuenow"),
    }));

  const afterLoad = await read();

  // --- 2) Autoplay: 2,2 s laufen lassen
  await page.waitForTimeout(2200);
  const afterAutoplay = await read();

  // --- 3) Pause per Button-Klick + Screenshot A
  await page.click("#play-btn");
  await page.waitForTimeout(700);
  const paused = await read();
  const clip = await page
    .locator(".map-wrap")
    .boundingBox();
  const shotA = await page.screenshot({ clip });

  // --- 4) Drag des Thumbs auf ~92 % der Reglerbreite
  const thumb = page.locator(".slider-wrap .dash-slider-thumb").first();
  const root = page.locator(".slider-wrap .dash-slider-root").first();
  const hb = await thumb.boundingBox();
  const rb = await root.boundingBox();
  let drag = "thumb/root fehlen";
  if (hb && rb) {
    await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
    await page.mouse.down();
    await page.mouse.move(rb.x + rb.width * 0.92, rb.y + rb.height / 2, {
      steps: 30,
    });
    await page.mouse.up();
    await page.waitForTimeout(1500);
    drag = "ok";
  }
  const afterDrag = await read();
  const shotB = await page.screenshot({ clip });

  // Pixel-Diff: hat sich das Bild der Karte sichtbar geaendert?
  let diff = 0;
  const n = Math.min(shotA.length, shotB.length);
  for (let i = 0; i < n; i++) if (shotA[i] !== shotB[i]) diff++;

  // --- 5) Mausrad: 5x runter = +5 Jahre
  await page.mouse.move(rb.x + rb.width * 0.5, rb.y + rb.height / 2);
  for (let i = 0; i < 5; i++) {
    await page.mouse.wheel(0, 120);
    await page.waitForTimeout(90);
  }
  await page.waitForTimeout(1200);
  const afterWheel = await read();

  return {
    afterLoad,
    afterAutoplay,
    paused,
    drag,
    afterDrag,
    pixelDiff: {
      bytesA: shotA.length,
      bytesB: shotB.length,
      diffBytes: diff,
      pct: +(100 * (diff / n)).toFixed(2),
    },
    afterWheel,
  };
}
