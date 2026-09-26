/* QA: Laderennen Plotly vs. Initial-Callback.
 * Verzoegert plotly.min.js um 3 s und laedt neu. Ohne Guard wrde der
 * Initial-Aufruf von ns.update "Plotly is not defined" werfen (sichtbar
 * im Console-Report des Runners). Mit Guard: kein Fehler, und nach dem
 * Laden heilt sich die Anzeige selbst (naechster Tick rendert alles).
 */
export default async function run(page) {
  await page.route("**/plotly.min.js", async (route) => {
    await page.waitForTimeout(3000);
    await route.continue();
  });
  await page.goto("http://127.0.0.1:8051/", { waitUntil: "domcontentloaded" });

  await page.waitForFunction(
    () =>
      document.querySelectorAll("#map3d canvas").length > 0 &&
      document.querySelector(".slider-wrap .dash-slider-thumb"),
    { timeout: 300000 }
  );
  // Plotly ist jetzt geladen; pruefen, dass die Anzeige sich selbst
  // geheilt hat (Autoplay-Ticks -> update -> top10 + Labels).
  await page.waitForTimeout(2500);
  const state = await page.evaluate(() => ({
    year: document.getElementById("year-label").textContent,
    playBtn: document.getElementById("play-btn").textContent,
    top10Title: (document.querySelector("#top10 .gtitle") || {}).textContent
      || null,
    plotlyGlobal: typeof window.Plotly,
  }));
  return state;
}
