export default async function run(page) {
  const t0 = Date.now();
  await page.waitForFunction(
    () => document.querySelectorAll('#map3d canvas').length > 0,
    { timeout: 60000 }
  );
  const waited = Date.now() - t0;
  const info = await page.evaluate(() => {
    const el = document.querySelector('#map3d .js-plotly-plot');
    return {
      hasData: !!el.data,
      nTraces: el.data ? el.data.length : -1,
      traceKeys: el.data ? Object.keys(el.data[1]) : [],
      zIsArray: el.data ? Array.isArray(el.data[1].z) : null,
      vc0: el.data && el.data[1].vertexcolor ? el.data[1].vertexcolor[0] : null,
      plotlyGlobal: typeof window.Plotly,
      className: el.className,
      year: document.getElementById('year-label').textContent,
    };
  });
  return { ...info, waitedMs: waited };
}
