/* QA: Greift man den Jahres-Regler WAHREND die Animation laeuft,
 * muss sie sofort pausieren (▶) und das Jahr darf nicht weiterlaufen.
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 150000 }
  );
  const read = () =>
    page.evaluate(() => ({
      year: document.getElementById("year-label").textContent,
      playBtn: document.getElementById("play-btn").textContent,
    }));

  // Autoplay laufen lassen bis das Jahr sichtbar weiterlaeuft
  let a = await read();
  const t0 = Date.now();
  while (Date.now() - t0 < 20000) {
    await page.waitForTimeout(500);
    const b = await read();
    if (b.year !== a.year && b.playBtn === "❚❚") {
      a = b;
      break;
    }
    a = b;
  }

  // Griff in den Regler (pointerdown ohne Button-Klick)
  const thumb = page.locator(".slider-wrap .dash-slider-thumb").first();
  const root = page.locator(".slider-wrap .dash-slider-root").first();
  const hb = await thumb.boundingBox();
  const rb = await root.boundingBox();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(600);
  const duringHold = await read();
  await page.mouse.move(rb.x + rb.width * 0.5, rb.y + rb.height / 2, {
    steps: 10,
  });
  await page.mouse.up();
  await page.waitForTimeout(800);
  const afterRelease = await read();

  // Nach dem Loslegen darf das Jahr eingefroren bleiben
  await page.waitForTimeout(1500);
  const frozen = await read();

  return {
    playingBefore: a,
    duringHold,
    afterRelease,
    frozen,
    pausedByGrab: duringHold.playBtn === "▶",
    yearFrozen: afterRelease.year === frozen.year,
  };
}
