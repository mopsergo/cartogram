/* QA: Kartogramm-Flaechen folgen dem Jahres-Slider (Snapshots + Interpolation).
 * USA-Spanne im Kartogramm muss 1820 vs ~2004 unterschiedlich sein,
 * waehrend die Original-Karte (map3d) konstant bleibt. z-Hoehen folgen.
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 300000 }
  );
  await page.click("#play-btn");
  await page.waitForTimeout(600);

  await page.addScriptTag({
    content: `
      (function () {
        function el(id) {
          var w = document.getElementById(id);
          return w && w.querySelector ? w.querySelector(".js-plotly-plot") : null;
        }
        function span(gdId, country) {
          var e = el(gdId);
          if (!e || !e.data) return null;
          for (var t = 0; t < e.data.length; t++) {
            var tr = e.data[t];
            if (tr.name && tr.name.indexOf(country) === 0 && tr.x) {
              return Math.round((Math.max.apply(null, tr.x)
                - Math.min.apply(null, tr.x)) * 10) / 10;
            }
          }
          return null;
        }
        function zmax(gdId) {
          var e = el(gdId);
          if (!e || !e.data) return null;
          var m = -Infinity;
          for (var t = 1; t < e.data.length - 1; t++) {
            var z = e.data[t].z; if (!z) continue;
            for (var i = 0; i < z.length; i++) if (z[i] > m) m = z[i];
          }
          return m === -Infinity ? null : Math.round(m * 100) / 100;
        }
        function read() {
          document.documentElement.dataset.cart = JSON.stringify({
            usaCart: span("map3d_cart", "USA"),
            usaOrig: span("map3d", "USA"),
            zCart: zmax("map3d_cart"),
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
      () => JSON.parse(document.documentElement.dataset.cart || "null")
    );

  const state1820 = await S();

  // Slider auf ~92 % ziehen (Jahr ~2004)
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
  await page.waitForTimeout(2500);
  const state2004 = await S();

  return {
    state1820,
    state2004,
    usaWaechstMitSlider:
      state2004.usaCart > state1820.usaCart * 1.2,
    origKonstant: state2004.usaOrig === state1820.usaOrig,
    zChanged: state1820.zCart !== state2004.zCart,
  };
}
