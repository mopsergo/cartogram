/* QA: No-Data-Trace (graue Flaechen) + Slider-Regression.
 * Bruecke (Main-World) liest Trace-Anzahl, No-Data-Namen und z-max.
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
        function el(id) {
          var w = document.getElementById(id);
          return w && w.querySelector ? w.querySelector(".js-plotly-plot") : null;
        }
        function read() {
          var t = el("map3d"), p = el("map3d_pc");
          var nd = t && t.data ? t.data[t.data.length - 1] : null;
          var zmax = -Infinity;
          if (t && t.data) {
            for (var k = 1; k < t.data.length - 1; k++) {
              var z = t.data[k].z; if (!z) continue;
              for (var i = 0; i < z.length; i++) if (z[i] > zmax) zmax = z[i];
            }
          }
          document.documentElement.dataset.state = JSON.stringify({
            nTotal: t && t.data ? t.data.length : -1,
            nPc: p && p.data ? p.data.length : -1,
            nodataName: nd ? nd.name : null,
            nodataHasCustomdata: nd ? !!nd.customdata : false,
            nodataZ: nd && nd.z ? Math.max.apply(null, nd.z) : null,
            zmaxTotal: zmax === -Infinity ? null : zmax,
            year: document.getElementById("year-label").textContent,
          });
        }
        setInterval(read, 200);
        read();
      })();
    `,
  });
  const S = () =>
    page.evaluate(
      () => JSON.parse(document.documentElement.dataset.state || "null")
    );

  const state0 = await S();
  await page.click("#play-btn");
  await page.waitForTimeout(300);

  // Slider-Regression: Karte muss weiterhin auf den Regler reagieren
  const thumb = page.locator(".slider-wrap .dash-slider-thumb").first();
  const root = page.locator(".slider-wrap .dash-slider-root").first();
  const hb = await thumb.boundingBox();
  const rb = await root.boundingBox();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.9, rb.y + rb.height / 2, {
    steps: 25,
  });
  await page.mouse.up();
  await page.waitForTimeout(1500);
  const state1 = await S();

  return {
    state0,
    state1,
    nodataTraceOk:
      state0.nodataName === "Keine Daten" && state0.nodataHasCustomdata,
    flatOk: state0.nodataZ === 0,
    tracesTotal: state0.nTotal,
    tracesPc: state0.nPc,
    sliderReactiert: state0.zmaxTotal !== state1.zmaxTotal,
    jahr: state1.year,
  };
}
