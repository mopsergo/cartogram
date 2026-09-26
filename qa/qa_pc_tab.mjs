/* QA: Tab "Pro Kopf" – Rendern, Slider-Update, Kamera-Schutz, Rueckschalter.
 * Bruecke (Main-World) liefert z-max beider Karten + PC-Kamera ins DOM.
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 150000 }
  );
  await page.click("#play-btn"); // Autoplay pausieren fuer deterministische Jahre
  await page.waitForTimeout(400);

  await page.addScriptTag({
    content: `
      (function () {
        function el(id) {
          var w = document.getElementById(id);
          return w && w.querySelector ? w.querySelector(".js-plotly-plot") : null;
        }
        function zmax(id) {
          var e = el(id);
          if (!e || !e.data) return null;
          var m = -Infinity;
          for (var t = 1; t < e.data.length; t++) {
            var z = e.data[t].z; if (!z) continue;
            for (var i = 0; i < z.length; i++) if (z[i] > m) m = z[i];
          }
          return m === -Infinity ? null : Math.round(m * 1000) / 1000;
        }
        function eye(id) {
          var e = el(id);
          var c = e && e.layout && e.layout.scene && e.layout.scene.camera;
          return c ? c.eye : null;
        }
        setInterval(function () {
          document.documentElement.dataset.state = JSON.stringify({
            zTotal: zmax("map3d"),
            zPc: zmax("map3d_pc"),
            camPc: eye("map3d_pc"),
          });
        }, 200);
      })();
    `,
  });

  const S = () =>
    page.evaluate(
      () => JSON.parse(document.documentElement.dataset.state || "null")
    );
  const year = () =>
    page.evaluate(() => document.getElementById("year-label").textContent);
  const isDefault = (c) =>
    !c || (Math.abs(c.x) < 0.05 && Math.abs(c.y - 1.28) < 0.05 &&
           Math.abs(c.z - 0.92) < 0.05);

  const state0 = await S();
  const year0 = await year();

  // --- Tab "Pro Kopf" oeffnen ---
  await page.click("#tab-pc");
  await page.waitForTimeout(1200);
  const pcVisible = await page.evaluate(() => {
    const pane = document.getElementById("map-pc");
    const canvases = document.querySelectorAll("#map-pc canvas");
    const c0 = canvases[0];
    const side = document.getElementById("top10_pc");
    const title = (document.querySelector("#top10_pc .gtitle") || {})
      .textContent;
    return {
      paneDisplay: pane.style.display,
      nCanvases: canvases.length,
      canvasW: c0 ? c0.clientWidth : 0,
      canvasH: c0 ? c0.clientHeight : 0,
      sideDisplay: side.style.display,
      top10Title: title,
      totalPaneHidden:
        document.getElementById("map-total").style.display === "none",
    };
  });
  const stateAfterTab = await S();

  // --- Slider-Zug: Pro-Kopf-Hoehen muessen sich aendern ---
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
  await page.waitForTimeout(1500);
  const stateAfterDrag = await S();
  const yearAfterDrag = await year();

  // --- PC-Karte drehen, dann Slider bewegen: Kamera muss bleiben ---
  const mb = await page.locator("#map-pc canvas").boundingBox();
  const cx = mb.x + mb.width / 2,
    cy = mb.y + mb.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 150, cy - 90, { steps: 15 });
  await page.mouse.up();
  await page.waitForTimeout(500);
  const camRotated = (await S()).camPc;

  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  // Thumb steht jetzt rechts -> zurueck auf ~40 % ziehen
  const hb2 = await thumb.boundingBox();
  await page.mouse.move(hb2.x + hb2.width / 2, hb2.y + hb2.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.4, rb.y + rb.height / 2, {
    steps: 20,
  });
  await page.mouse.up();
  await page.waitForTimeout(1200);
  const stateAfterSecondDrag = await S();
  const yearAfterSecondDrag = await year();

  // --- Zurueck auf Tab "Gesamt" ---
  await page.click("#tab-total");
  await page.waitForTimeout(900);
  const backToTotal = await page.evaluate(() => {
    const canvases = document.querySelectorAll("#map-total canvas");
    const c0 = canvases[0];
    return {
      paneDisplay: document.getElementById("map-total").style.display,
      canvasW: c0 ? c0.clientWidth : 0,
      canvasH: c0 ? c0.clientHeight : 0,
      top10Visible:
        document.getElementById("top10").style.display === "block",
      pcPaneHidden:
        document.getElementById("map-pc").style.display === "none",
    };
  });
  const stateFinal = await S();

  return {
    year0,
    state0,
    pcVisible,
    stateAfterTab,
    pcZChangedByDrag:
      stateAfterTab.zPc !== stateAfterDrag.zPc,
    stateAfterDrag,
    yearAfterDrag,
    camRotatedNichtDefault: !isDefault(camRotated),
    camRotated,
    camSurvivedSlider: !isDefault(stateAfterSecondDrag.camPc),
    stateAfterSecondDrag,
    yearAfterSecondDrag,
    backToTotal,
    stateFinal,
  };
}
