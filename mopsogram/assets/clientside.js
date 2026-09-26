/* Clientseitige Logik: Jahres-Animation & Karten-Update ohne Server-Last */
window.dash_clientside = window.dash_clientside || {};
const ns = (window.dash_clientside.map3d = {});

const YEAR0 = 1820;
const YEAR1 = 2020;
let currentYear = YEAR0; // aktuell angezeigtes Jahr (fuer Mausrad-Scrollen)
let lastCamera = null;  // letzte Nutzer-Kamera (Drehung/Zoom)

function fmt(v, digits) {
  return (v == null ? 0 : v).toLocaleString(
    "de-DE", { maximumFractionDigits: digits == null ? 1 : digits });
}

function heightOf(v, mode, vmax, hmax) {
  if (!v || v <= 0) return 0;
  const t = vmax > 0 ? Math.min(v / vmax, 1) : 0;
  let u;
  if (mode === "linear") u = t;
  else if (mode === "sqrt") u = Math.sqrt(t);
  else u = Math.log10(1 + 99 * t) / 2;
  return hmax * u;
}

/* Kamera-Schutz: Plotly uebernimmt bei jedem Replot (restyle/tick) die
   Kamera aus layout.scene.camera – die Nutzer-Rotation landet dort aber
   erst beim Loslassen (saveLayout auf mouseup). Trifft ein Replot
   waehrend der Drehung, springt die Ansicht zurueck. Deshalb: Live-Kamera
   aus den Events mitlesen und nach jedem Restyle zurueckschreiben. */
function onCameraEvent(e) {
  const cam = e && e["scene.camera"];
  if (cam) lastCamera = cam;
}

function trackCamera(gd) {
  if (gd._camTracked) return;
  gd._camTracked = true;
  gd.on("plotly_relayout", onCameraEvent);   // nach Loslassen/Zoom
  gd.on("plotly_relayouting", onCameraEvent); // waehrend der Drehung
}

/* Live-Kamera im Layout-Format ({up, center, eye, projection}) – direkt
   aus dem Scene-Objekt, unabhaengig vom (evtl. veralteten) layout. */
function liveCamera(gd) {
  try {
    const scene = gd._fullLayout && gd._fullLayout.scene;
    const so = scene && scene._scene;
    if (so && typeof so.getCamera === "function") return so.getCamera();
  } catch (e) { /* unten Fallback */ }
  return lastCamera;
}

/* Numerischer Vergleich (Toleranz) statt JSON-String: verhindert
   Relayout-Schleifen durch Float-Jitter. */
function sameCam(a, b) {
  if (!a || !b) return !a && !b;
  for (const k of ["up", "center", "eye"]) {
    const u = a[k], v = b[k];
    if (!u || !v) return false;
    for (const c of ["x", "y", "z"]) {
      if (Math.abs((u[c] || 0) - (v[c] || 0)) > 1e-6) return false;
    }
  }
  return true;
}

/* Läuft gerade eine Kamera-Interaktion (Maus-Drag auf der Karte)? */
function cameraDragActive(gd) {
  try {
    const so = gd._fullLayout.scene._scene;
    const ml = so && so.camera && so.camera.mouseListener;
    return !!(ml && ml.buttons);
  } catch (e) {
    return false;
  }
}

/* Plotly-Element einer Karte holen. Achtung: Ab Dash 4 ist die Graph-id
   nur der Wrapper (div.dash-graph), das eigentliche Plotly-Element
   (.datasets, .layout) ist das Kindelement .js-plotly-plot. Aeltere
   Dash-Versionen legen die id direkt auf das Plotly-Element. */
function graphEl(id) {
  const w = document.getElementById(id);
  if (!w) return null;
  if (w.data) return w;                       // Dash <= 3
  const p = w.querySelector(".js-plotly-plot"); // Dash 4: Wrapper + Kind
  return p && p.data ? p : null;
}

/* Naechstes Jahr (Autoplay). Wartet, bis die Karte initial gerendert ist. */
ns.tick = function (n, year) {
  const gd = graphEl("map3d");
  if (!gd || !gd.data) return window.dash_clientside.no_update;
  currentYear = year;
  return year >= YEAR1 ? YEAR0 : year + 1;
};

/* Play/Pause: reiner Toggle ueber den Button. Das Pausieren beim
   Jahres-Regler uebernehmen die DOM-Listener unten (pointerdown,
   focusin, wheel) – drag_value als Callback-Input faellt weg, weil der
   Slider es in Dash 4 einmal beim Mount feuert und die App sonst
   nie von selbst starten wuerde. */
ns.playState = function (nClicks, playing) {
  playing = !playing;
  return [playing, !playing, playing ? "❚❚" : "▶",
          playing ? "btn active" : "btn"];
};

/* Hoehen eines Jahres in eine der beiden Karten restylen – inklusive
   Kamera-Schutz: kein Replot waehrend der Nutzer die Kamera dreht,
   Live-Kamera als Sicherheitsnetz ueber den Restyle retten. */
function restyleMap(gd, store, yi, mode, opts) {
  if (!gd || !gd.data || !window.Plotly) return;
  if (cameraDragActive(gd)) return; // Drehung laeuft -> naechster Wertwechsel
  trackCamera(gd);

  const zs = [];
  const names = [];
  for (let t = 0; t < store.ztop.length; t++) {
    const ci = store.traceCountry[t];
    const v = opts.values[ci][yi];
    const h = heightOf(v, mode, opts.vmax, store.hmax);
    const mask = store.ztop[t];
    const z = new Array(mask.length);
    for (let i = 0; i < mask.length; i++) z[i] = mask[i] ? h : 0;
    zs.push(z);
    names.push(store.names[ci] + ": " + fmt(v, opts.digits) + " " + opts.unit);
  }

  const cam = liveCamera(gd);
  Plotly.restyle(gd, { z: zs, name: names }, store.traceIdx).then(
    function () {
      const now = gd.layout && gd.layout.scene && gd.layout.scene.camera;
      if (cam && !sameCam(cam, now)) {
        Plotly.relayout(gd, { "scene.camera": cam });
      }
    }
  );
}

/* Top-10-Balkendiagramm (Seitenpanel) via Plotly.react neu zeichnen. */
function renderTop10(elId, tops, store, title, digits) {
  if (!window.Plotly) return;  // Bundle laedt noch -> naechster Tick holt nach
  const bar = document.getElementById(elId);
  if (!bar || !tops) return;
  const rows = tops.slice().reverse();
  Plotly.react(
    bar,
    {
      data: [
        {
          type: "bar",
          orientation: "h",
          y: rows.map((r) => store.names[r[0]]),
          x: rows.map((r) => r[1]),
          marker: { color: rows.map((r) => store.colors[r[0]]) },
          text: rows.map((r) => fmt(r[1], digits)),
          textposition: "auto",
          textfont: { color: "#0d1117", size: 10 },
          hoverinfo: "skip",
        },
      ],
      layout: {
        margin: { l: 8, r: 14, t: 34, b: 6 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { color: "#c9d4e3", family: "system-ui, sans-serif", size: 11 },
        title: {
          text: title,
          font: { size: 13, color: "#e8eef7" },
          x: 0.06,
          xanchor: "left",
          y: 0.97,
        },
        xaxis: { gridcolor: "#232d3b", zeroline: false, tickfont: { size: 9 } },
        bargap: 0.35,
      },
    },
    { displayModeBar: false, responsive: true }
  );
}

/* Jahres-Update: beide Karten restylen, Panels + Labels erneuern,
 * Kartogramm-Flaechen folgen dem Bevoelkerungsjahr (interpoliert). */
let lastCartYear = null;

function restyleCartXY(gd, store, year) {
  if (!gd || !gd.data || !window.Plotly) return;
  if (!store.cart_xy || !store.cart_vmap) return;
  if (cameraDragActive(gd)) return;       // Kamera-Drag: naechster Tick
  if (year === lastCartYear) return;
  lastCartYear = year;

  const years = store.cart_years;
  let i0 = 0;
  while (i0 < years.length - 2 && years[i0 + 1] <= year) i0++;
  const y0 = years[i0], y1 = years[i0 + 1];
  const f = Math.max(0, Math.min(1, (year - y0) / (y1 - y0)));
  const a = store.cart_xy[i0], b = store.cart_xy[i0 + 1];

  const xs = [], ys = [];
  for (let t = 0; t < store.cart_vmap.length; t++) {
    const rows = store.cart_vmap[t];
    const tx = new Array(rows.length);
    const ty = new Array(rows.length);
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r < 0) {
        // Kein Snapshot fuer diesen Vertex: null-Separator beibehalten,
        // Mesh-Vertices an aktueller Position halten (nie null in Mesh3d).
        const cur = gd.data[t];
        tx[i] = cur.x && cur.x[i] != null ? cur.x[i] : null;
        ty[i] = cur.y && cur.y[i] != null ? cur.y[i] : null;
        continue;
      }
      tx[i] = a[2 * r] + f * (b[2 * r] - a[2 * r]);
      ty[i] = a[2 * r + 1] + f * (b[2 * r + 1] - a[2 * r + 1]);
    }
    xs.push(tx);
    ys.push(ty);
  }

  trackCamera(gd);
  const cam = liveCamera(gd);
  const idx = [];
  for (let i = 0; i < store.cart_vmap.length; i++) idx.push(i);
  Plotly.restyle(gd, { x: xs, y: ys }, idx).then(function () {
    const now = gd.layout && gd.layout.scene && gd.layout.scene.camera;
    if (cam && !sameCam(cam, now)) {
      Plotly.relayout(gd, { "scene.camera": cam });
    }
  });
}

ns.update = function (year, mode, store) {
  currentYear = year;
  const no = window.dash_clientside.no_update;
  /* plotly.min.js (3,5 MB) laedt asynchron – der Initial-Aufruf dieses
     Callbacks kann frueher feuern als das Bundle bereit ist. Dann hier
     ruhig abwarten: der naechste Animations-Tick (280 ms) holt alles
     nach. Ohne diesen Guard: "Plotly is not defined". */
  if (!window.Plotly) return [no, no, no];
  if (!store) return [no, String(year), ""];
  const yi = store.years.indexOf(year);
  if (yi < 0) return [no, String(year), ""];

  restyleMap(graphEl("map3d"), store, yi, mode,
             { values: store.values, vmax: store.vmax,
               unit: "Mtoe", digits: 1 });
  if (store.values_pc) {
    restyleMap(graphEl("map3d_pc"), store, yi, mode,
               { values: store.values_pc, vmax: store.vmax_pc,
                 unit: "kWh/Kopf", digits: 0 });
  }
  restyleMap(graphEl("map3d_cart"), store, yi, mode,
             { values: store.values, vmax: store.vmax,
               unit: "Mtoe", digits: 1 });
  restyleCartXY(graphEl("map3d_cart"), store, year);

  renderTop10("top10", store.tops[yi], store, "Top 10 · " + year, 1);
  if (store.tops_pc) {
    renderTop10("top10_pc", store.tops_pc[yi], store,
                "Top 10 pro Kopf · " + year, 0);
  }

  let badge = "Welt: " + fmt(store.total[yi]) + " Mtoe";
  if (store.avg_pc) {
    badge += " · Ø " + fmt(store.avg_pc[yi], 0) + " kWh/Kopf";
  }
  return [no, String(year), badge];
};

/* ---- Jahres-Regler: sofort pausieren + mit dem Mausrad scrollen ---- */

/* Autoplay anhalten: Interval stoppen, Store und Play-Button umschalten. */
function pausePlayback() {
  const dc = window.dash_clientside;
  if (typeof dc.set_props !== "function") return;
  dc.set_props("playing", { data: false });
  dc.set_props("interval", { disabled: true });
  dc.set_props("play-btn", { children: "▶", className: "btn" });
}

/* Griff in den Regler: sofort pausieren (Maus/Touch/Stift). drag_value
   feuert erst bei der ersten Bewegung – der Tick waere sonst schneller. */
document.addEventListener("pointerdown", function (e) {
  const t = e.target;
  if (t && t.closest && t.closest(".slider-wrap")) pausePlayback();
});

/* Tastatur: Fokus auf den Regler (Tab/Pfeiltasten) pausiert ebenfalls. */
document.addEventListener("focusin", function (e) {
  const t = e.target;
  if (t && t.closest && t.closest(".slider-wrap")) pausePlayback();
});

/* Mausrad ueber dem Regler: Jahr fuer Jahr ueber die Zeitachse scrollen. */
document.addEventListener(
  "wheel",
  function (e) {
    const t = e.target;
    if (!t || !t.closest || !t.closest(".slider-wrap")) return;
    e.preventDefault();
    pausePlayback();
    const dc = window.dash_clientside;
    if (typeof dc.set_props !== "function") return;
    const y = Math.max(
      YEAR0,
      Math.min(YEAR1, currentYear + (e.deltaY > 0 ? 1 : -1))
    );
    dc.set_props("year-slider", { value: y });
  },
  { passive: false }
);

/* ---- Tabs: Gesamt (Mtoe) / Pro Kopf (kWh) / Kartogramm ----------------
 * Rein im DOM: Buttons + Anzeige umschalten. Plotly hat den Graph des
 * verborgenen Tabs mit 0x0 px gerendert -> beim Wechsel neu vermessen. */
function showTab(which) {
  const panes = { total: "map-total", pc: "map-pc", cart: "map-cart" };
  const graphs = { total: "map3d", pc: "map3d_pc", cart: "map3d_cart" };
  const sides = { total: "top10", pc: "top10_pc", cart: "top10" };
  for (const key of Object.keys(panes)) {
    const pane = document.getElementById(panes[key]);
    if (pane) pane.style.display = key === which ? "block" : "none";
    const side = document.getElementById(sides[key]);
    if (side) side.style.display = key === which ? "block" : "none";
    const btn = document.getElementById(
      key === "total" ? "tab-total"
      : key === "pc" ? "tab-pc" : "tab-cart");
    if (btn) btn.className = "tabbtn" + (key === which ? " active" : "");
  }
  const gd = graphEl(graphs[which]);
  if (gd && window.Plotly && Plotly.Plots && Plotly.Plots.resize) {
    Plotly.Plots.resize(gd);
  }
}

document.addEventListener("click", function (e) {
  const t = e.target;
  if (!t || !t.closest) return;
  if (t.closest("#tab-pc")) showTab("pc");
  else if (t.closest("#tab-cart")) showTab("cart");
  else if (t.closest("#tab-total")) showTab("total");
});
