export default async function run(page) {
  const t0 = Date.now();
  const states = [];
  // Poll bis zu 90 s: wann verschwindet "pending", wann erscheint .datasets?
  while (Date.now() - t0 < 90000) {
    const s = await page.evaluate(() => {
      const el = document.querySelector('#map3d .js-plotly-plot');
      const canvases = document.querySelectorAll('#map3d canvas');
      return {
        pending: el ? el.className.includes('pending') : null,
        hasData: el ? !!el.data : false,
        nTraces: el && el.data ? el.data.length : -1,
        canvases: canvases.length,
        bodyText: document.body.innerText.slice(0, 60).replace(/\n/g, ' | '),
      };
    });
    states.push({ t: Date.now() - t0, ...s });
    if (s.hasData) break;
    await page.waitForTimeout(2000);
  }
  const final = states[states.length - 1];
  const timings = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0];
    const res = performance.getEntriesByType('resource')
      .filter((r) => r.duration > 300)
      .map((r) => ({ name: r.name.split('/').slice(-1)[0], dur: Math.round(r.duration), size: r.transferSize }));
    return { domContentLoaded: Math.round(nav.domContentLoadedEventEnd), slowResources: res.slice(0, 12) };
  });
  return { final, states, timings };
}
