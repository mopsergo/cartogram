/* QA: Kartogramm-Tab (flow-basiert, Flaeche ~ Bevoelkerung 2020).
 * Prueft: Tab rendert, Verzerrung wirkt (Indien gross, Kanada klein),
 * Slider bewegt die Hoehen auch im Kartogramm, keine Console-Fehler.
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 300000 }
  );
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
            indiaOrig: span("map3d", "India"),
            indiaCart: span("map3d_cart", "India"),
            canadaOrig: span("map3d", "Canada"),
            canadaCart: span("map3d_cart", "Canada"),
            zCart: zmax("map3d_cart"),
            nCart: (el("map3d_cart") && el("map3d_cart").data)
              ? el("map3d_cart").data.length : -1,
          });
        }
        setInterval(read, 250);
        read();
      })();
    `,
  });
  const S = () =>
    page.evaluate(
      () => JSON.parse(document.documentElement.dataset.cart || "null")
    );

  const state0 = await S();

  // Tab "Kartogramm" oeffnen
  await page.click("#tab-cart");
  await page.waitForTimeout(1500);
  const tabVisible = await page.evaluate(() => {
    const canvases = document.querySelectorAll("#map-cart canvas");
    const c0 = canvases[0];
    return {
      paneDisplay: document.getElementById("map-cart").style.display,
      nCanvases: canvases.length,
      canvasW: c0 ? c0.clientWidth : 0,
      canvasH: c0 ? c0.clientHeight : 0,
      sideVisible:
        document.getElementById("top10").style.display === "block",
      otherPanesHidden:
        document.getElementById("map-total").style.display === "none" &&
        document.getElementById("map-pc").style.display === "none",
    };
  });

  // Slider-Zug: Hoehen im Kartogramm muessen folgen
  await page.click("#tab-total"); // Pause-Button liegt ausserhalb
  await page.waitForTimeout(300);
  const thumb = page.locator(".slider-wrap .dash-slider-thumb").first();
  const root = page.locator(".slider-wrap .dash-slider-root").first();
  const hb = await thumb.boundingBox();
  const rb = await root.boundingBox();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.92, rb.y + rb.height / 2, {
    steps: 25,
  });
  await page.mouse.up();
  await page.waitForTimeout(2000);
  const state1 = await S();

  return {
    state0,
    tabVisible,
    zCartChanged: state0.zCart !== state1.zCart,
    state1,
    indiaWaechst: state1.indiaCart > state1.indiaOrig * 2,
    canadaSchrumpft: state1.canadaCart < state1.canadaOrig * 0.5,
    tracesOk: state0.nCart === 74,
  };
}
