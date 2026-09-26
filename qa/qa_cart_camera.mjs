/* QA: Kamera im Kartogramm-Tab ueberlebt Slider-Zug (x/y-Restyle!).
 * Ablauf: Pause -> Tab Kartogramm -> Karte drehen -> Slider ziehen
 * -> Kamera muss erhalten bleiben, Flaechen muessen sich aendern.
 */
export default async function run(page) {
  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 300000 }
  );
  await page.click("#play-btn");
  await page.waitForTimeout(500);
  await page.click("#tab-cart");
  await page.waitForTimeout(1500);

  await page.addScriptTag({
    content: `
      (function () {
        function el(id) {
          var w = document.getElementById(id);
          return w && w.querySelector ? w.querySelector(".js-plotly-plot") : null;
        }
        function eye() {
          var e = el("map3d_cart");
          var c = e && e.layout && e.layout.scene && e.layout.scene.camera;
          return c ? c.eye : null;
        }
        function usaSpan() {
          var e = el("map3d_cart");
          if (!e || !e.data) return null;
          for (var t = 0; t < e.data.length; t++) {
            var tr = e.data[t];
            if (tr.name && tr.name.indexOf("USA") === 0 && tr.x) {
              return Math.round((Math.max.apply(null, tr.x)
                - Math.min.apply(null, tr.x)) * 10) / 10;
            }
          }
          return null;
        }
        function read() {
          document.documentElement.dataset.q = JSON.stringify({
            eye: eye(),
            usa: usaSpan(),
            year: document.getElementById("year-label").textContent,
          });
        }
        setInterval(read, 150);
        read();
      })();
    `,
  });
  const S = () =>
    page.evaluate(() => JSON.parse(document.documentElement.dataset.q || "null"));
  const isDefault = (c) =>
    !c || (Math.abs(c.x) < 0.05 && Math.abs(c.y - 1.28) < 0.05 &&
           Math.abs(c.z - 0.92) < 0.05);

  const before = await S();

  // Kamera im Kartogramm drehen
  const mb = await page.locator("#map-cart canvas").boundingBox();
  const cx = mb.x + mb.width / 2, cy = mb.y + mb.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 150, cy - 90, { steps: 15 });
  await page.mouse.up();
  await page.waitForTimeout(600);
  const rotated = await S();

  // Slider ziehen -> x/y-Restyle + Interpolation
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
  const afterSlider = await S();

  return {
    before,
    rotated: rotated.eye,
    rotationOk: !isDefault(rotated.eye),
    afterSlider: afterSlider.eye,
    cameraSurvived: !isDefault(afterSlider.eye),
    year: afterSlider.year,
    usaBefore: rotated.usa,
    usaAfter: afterSlider.usa,
    areaChanged: rotated.usa !== afterSlider.usa,
  };
}
