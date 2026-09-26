/* QA: Kamera-Schutz nach Fix – das exakte Nutzerverhalten.
 * 1. Animation laeuft (ohne Pause!): Karte drehen -> Kamera muss DREI
 *    Sekunden lang (≈10 Restyle-Ticks) gedreht bleiben.
 * 2. Slider greifen (pausiert) + ziehen -> Kamera bleibt.
 * 3. Zoom-Aenderung der Kamera via plotly_relayout zaehlen (Beweis, dass
 *    der Tracker hoert).
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 150000 }
  );

  await page.addScriptTag({
    content: `
      (function () {
        var ev = { relayout: 0, relayouting: 0 };
        function read() {
          var gd = document.querySelector("#map3d .js-plotly-plot");
          var c = gd && gd.layout && gd.layout.scene && gd.layout.scene.camera;
          document.documentElement.dataset.cam =
            c ? JSON.stringify(c.eye) : "null";
          document.documentElement.dataset.ev = JSON.stringify(ev);
        }
        var gd = document.querySelector("#map3d .js-plotly-plot");
        if (gd && gd.on) {
          gd.on("plotly_relayout", function (e) {
            if (e && e["scene.camera"]) ev.relayout++;
          });
          gd.on("plotly_relayouting", function (e) {
            if (e && e["scene.camera"]) ev.relayouting++;
          });
        }
        setInterval(read, 200);
        read();
      })();
    `,
  });

  const cam = () =>
    page.evaluate(() => document.documentElement.dataset.cam || "?");
  const ev = () =>
    page.evaluate(() => document.documentElement.dataset.ev || "?");
  const year = () =>
    page.evaluate(() => document.getElementById("year-label").textContent);
  const playBtn = () =>
    page.evaluate(() => document.getElementById("play-btn").textContent);

  const isDefault = (eye) =>
    eye &&
    Math.abs(eye.x) < 0.05 &&
    Math.abs(eye.y - 1.28) < 0.05 &&
    Math.abs(eye.z - 0.92) < 0.05;
  const parse = (raw) => {
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  };

  // Autoplay laeuft los (App startet spielend)
  await page.waitForTimeout(1200);
  const camDefault = await cam();
  const btnAtStart = await playBtn();

  // --- 1) Drehen WAHREND die Animation laeuft ---
  const mb = await page.locator("#map3d canvas").boundingBox();
  const cx = mb.x + mb.width / 2,
    cy = mb.y + mb.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 150, cy - 90, { steps: 15 });
  await page.mouse.up();
  await page.waitForTimeout(350);
  const camAfterRotate = await cam();

  // 3 s Autoplay: viele Restyle-Ticks gegen die gedrehte Kamera
  await page.waitForTimeout(3000);
  const camAfterTicks = await cam();
  const yearAfterTicks = await year();

  // --- 2) Slider greifen + ziehen (pausiert dabei automatisch) ---
  const thumb = page.locator(".slider-wrap .dash-slider-thumb").first();
  const root = page.locator(".slider-wrap .dash-slider-root").first();
  const hb = await thumb.boundingBox();
  const rb = await root.boundingBox();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.92, rb.y + rb.height / 2, {
    steps: 30,
  });
  await page.mouse.up();
  await page.waitForTimeout(1200);
  const camAfterSlider = await cam();
  const yearAfterSlider = await year();
  const btnAfter = await playBtn();
  const events = await ev();

  return {
    btnAtStart,
    camDefault,
    rotatedNichtDefault: !isDefault(parse(camAfterRotate)),
    camAfterRotate,
    survivedTicks: !isDefault(parse(camAfterTicks)),
    camAfterTicks,
    yearAfterTicks,
    camAfterSlider,
    survivedSlider: !isDefault(parse(camAfterSlider)),
    yearAfterSlider,
    btnAfter,
    events,
  };
}
