"""
Dash (Flask) App: 3D-Weltkarte des Energieverbrauchs je Land, 1820-2020.

- Jedes Land wird als extrudiertes Prisma (plotly Mesh3d) dargestellt,
  die Hoehe ueber der gesamten Landesflaeche = Energieverbrauch (Mtoe).
- Jahres-Slider + Autoplay; die Animation laeuft komplett clientseitig
  (Plotly.restyle), daher ohne Server-Roundtrips fluessig.
- Jahres-Regler frei scrollbar: Ziehen oder Mausrad pausiert den
  Autoplay automatisch (Autoplay-Tick ueberschreibt den Regler nie).
- Zwei Tabs: 3D-Weltkarte Gesamt (Mtoe) und Pro Kopf (kWh, Verbruach
  geteilt durch Bevoelkerung, TableP2) – gleiche Steuerung, die
  Kamera-Orientierung bleibt beim Scrollen erhalten.
- Dritter Tab "Kartogramm": Flaeche je Land proportional zur Bevoelkerung
  2020 (flow-basiert, Gastner/Seguy/More, PNAS 2018), Hoehe weiterhin
  Gesamtverbrauch – gleiche Slider-Steuerung.
- Seitliches Top-10-Panel, Hoehenskalierung linear / Wurzel / log.

Start:  python app.py   ->  http://127.0.0.1:8050
"""
import copy

import plotly.graph_objects as go
from dash import Dash, ClientsideFunction, Input, Output, State, dcc, html

import cartogram
import percapita
from meshdata import MACRO_COLORS, MACRO_LABELS, build

YEAR0, YEAR1 = 1820, 2020

# ------------------------------------------------------------------ Daten
coast, mesh_traces, store, nodata = build(year0=YEAR0, mode="sqrt")
store.update(percapita.compute(store))
pc_traces = percapita.build_traces(mesh_traces, store,
                                   year0=YEAR0, mode="sqrt")

# Kartogramm: Flaeche ~ Bevoelkerung, Snapshots je 10 Jahre (gecacht),
# dazwischen interpoliert die App clientseitig mit dem Slider.
CART_YEARS = list(range(YEAR0, YEAR1 + 1, 10))
cart_disps = cartogram.snapshots(store, CART_YEARS)
cart_traces = cartogram.build_traces(mesh_traces, store,
                                      cart_disps[YEAR0],
                                      year0=YEAR0, mode="sqrt")

# Snapshots in den Store: Original-Vertices + verzerrte Positionen je
# Jahrzehnt + Zuordnung Trace-Vertex -> Zeile (fuer die Interpolation).
_orig = cartogram.orig_xy(store["names"])
store["cart_years"] = CART_YEARS
store["cart_orig"] = _orig
store["cart_xy"] = []
for _y in CART_YEARS:
    _d = cart_disps[_y]
    _flat = []
    for _i in range(0, len(_orig), 2):
        _nx, _ny = _d.get((round(_orig[_i], 9), round(_orig[_i + 1], 9)),
                          (_orig[_i], _orig[_i + 1]))
        _flat.append(round(_nx, 3))
        _flat.append(round(_ny, 3))
    store["cart_xy"].append(_flat)
store["cart_vmap"] = cartogram.vertex_rows(
    _orig, [coast, *mesh_traces, nodata])


def _base_figure(data):
    f = go.Figure(data=data)
    f.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#141a24", bordercolor="#2a3644",
                        font=dict(color="#e8eef7")),
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="manual",
            aspectratio=dict(x=2.0, y=1.0, z=0.45),
            camera=dict(eye=dict(x=0.0, y=1.28, z=0.92),
                        center=dict(x=0.0, y=-0.04, z=-0.04),
                        up=dict(x=0, y=0, z=1)),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    return f


fig = _base_figure([coast, *mesh_traces, nodata])
fig_pc = _base_figure(
    [copy.deepcopy(coast), *pc_traces, copy.deepcopy(nodata)])
fig_cart = _base_figure(
    [cartogram.patch_trace(coast, cart_disps[YEAR0]), *cart_traces,
     cartogram.patch_trace(nodata, cart_disps[YEAR0])])

# ------------------------------------------------------------------ App
app = Dash(__name__, title="Energieverbrauch 3D · 1820–2020")
server = app.server  # fuer gunicorn & Co.

MACRO_ORDER = ["WE", "EE", "Af", "ME", "As", "LA", "O", ""]
used_macros = {m for m in store["macro"]}
legend_chips = [
    html.Span(
        [html.Span(className="dot",
                    style={"background": MACRO_COLORS[m]}),
         MACRO_LABELS.get(m, m)],
        className="chip",
    )
    for m in MACRO_ORDER if m in used_macros
]


def _de_num(v):
    return f"{v:,.1f}".translate(str.maketrans({",": "\u202f", ".": ","}))


layout = html.Div(
    className="app-shell",
    children=[
        # ------------------------------------------------ Kopfzeile
        html.Header(
            className="topbar",
            children=[
                html.Div(
                    className="brand",
                    children=[
                        html.H1("Energieverbrauch pro Land · 1820–2020"),
                        html.P("3D-Weltkarte · Säulenhöhe über der "
                               "Landesfläche = Jahresverbrauch (Mtoe) "
                               "bzw. Verbrauch pro Kopf (kWh)"),
                    ],
                ),
                html.Div(className="legend", children=legend_chips),
            ],
        ),
        # ------------------------------------------------ Steuerung
        html.Div(
            className="controls",
            children=[
                html.Button("❚❚", id="play-btn", title="Abspielen / Pause",
                            className="btn active", n_clicks=0),
                html.Div(
                    className="slider-wrap",
                    title="Ziehen oder Mausrad: Jahr wählen · "
                          "pausiert die Animation",
                    children=dcc.Slider(
                        id="year-slider",
                        min=YEAR0,
                        max=YEAR1,
                        step=1,
                        value=YEAR0,
                        marks={y: str(y) for y in
                               (1820, 1850, 1900, 1950, 2000, 2020)},
                        updatemode="drag",
                    ),
                ),
                html.Div(
                    className="year-badge",
                    children=[
                        html.Div(str(YEAR0), id="year-label"),
                        html.Div(
                            f"Welt: {_de_num(store['total'][0])} Mtoe"
                            f" · Ø {_de_num(store['avg_pc'][0])} kWh/Kopf",
                            id="total-label"),
                    ],
                ),
                dcc.Dropdown(
                    id="scale-dd",
                    options=[
                        {"label": "Höhe: Wurzel", "value": "sqrt"},
                        {"label": "Höhe: Linear", "value": "linear"},
                        {"label": "Höhe: Log", "value": "log"},
                    ],
                    value="sqrt",
                    clearable=False,
                    className="scale-dd",
                ),
            ],
        ),
        # ------------------------------------------------ Karte + Panel
        html.Div(
            className="main",
            children=[
                html.Div(
                    className="map-col",
                    children=[
                        html.Div(
                            className="tabbar",
                            children=[
                                html.Button("Gesamt · Mtoe", id="tab-total",
                                            className="tabbtn active",
                                            n_clicks=0),
                                html.Button("Pro Kopf · kWh", id="tab-pc",
                                            className="tabbtn", n_clicks=0),
                                html.Button("Kartogramm", id="tab-cart",
                                            className="tabbtn", n_clicks=0,
                                            title="Fläche ∝ Bevölkerung "
                                                  "des gewählten Jahres "
                                                  "(Dekaden-Snapshots, "
                                                  "interpoliert) · Höhe = "
                                                  "Gesamtverbrauch · "
                                                  "flow-basiert nach "
                                                  "Gastner et al., PNAS "
                                                  "2018"),
                            ],
                        ),
                        html.Div(
                            id="map-total", className="pane",
                            children=dcc.Graph(
                                id="map3d",
                                figure=fig,
                                config={"displaylogo": False,
                                        "responsive": True},
                                style={"width": "100%", "height": "100%"},
                            ),
                        ),
                        html.Div(
                            id="map-pc", className="pane",
                            style={"display": "none"},
                            children=dcc.Graph(
                                id="map3d_pc",
                                figure=fig_pc,
                                config={"displaylogo": False,
                                        "responsive": True},
                                style={"width": "100%", "height": "100%"},
                            ),
                        ),
                        html.Div(
                            id="map-cart", className="pane",
                            style={"display": "none"},
                            children=dcc.Graph(
                                id="map3d_cart",
                                figure=fig_cart,
                                config={"displaylogo": False,
                                        "responsive": True},
                                style={"width": "100%", "height": "100%"},
                            ),
                        ),
                    ],
                ),
                html.Div(
                    className="side",
                    children=[
                        html.Div(id="top10", className="top10"),
                        html.Div(id="top10_pc", className="top10",
                                 style={"display": "none"}),
                    ],
                ),
            ],
        ),
        # ------------------------------------------------ Fusszeile
        html.Footer(
            className="foot",
            children=[
                "Daten: TableA13_energy_consumption_per_country_annual.csv · "
                "Mtoe = Million Tonnen Öl-Äquivalent · Bevölkerung: "
                "TableP2_population_per_country_annual.csv (Pro Kopf in "
                "kWh, 1 Mtoe = 11,63 TWh) · Der Datensatz umfasst 72 Länder "
                "– flache graue Flächen = keine Daten im Datensatz · "
                "Kartogramm-Tab: Fläche ∝ Bevölkerung des gewählten Jahres "
                "(flow-basiert nach Gastner, Seguy &amp; More, PNAS 2018; "
                "Dekaden-Snapshots vorberechnet, dazwischen interpoliert – "
                "Vorablauf: python build_cartograms.py) · "
                "Geometrien: Natural Earth 110 m · Historische Aggregate "
                "(F. USSR, Czechoslovakia, Yugoslavia, Eritrea &amp; "
                "Ethiopia) als Verbund der Mitgliedsländer · Höhenachse "
                "zur Lesbarkeit überhöht.",
            ],
        ),
        # ------------------------------------------------ Unsichtbares
        dcc.Interval(id="interval", interval=280, n_intervals=0,
                     disabled=False),
        dcc.Store(id="store", data=store),
        dcc.Store(id="playing", data=True),
    ],
)
app.layout = layout


# --------------------------------------------------------- Callbacks
# Play/Pause: Der Button toggelt (rein clientseitig, kein Server-Roundtrip).
# Das Pausieren beim Griff in den Jahres-Regler uebernehmen die DOM-Listener
# in assets/clientside.js (pointerdown / focusin / wheel via set_props).
app.clientside_callback(
    ClientsideFunction(namespace="map3d", function_name="playState"),
    Output("playing", "datasets"),
    Output("interval", "disabled"),
    Output("play-btn", "children"),
    Output("play-btn", "className"),
    Input("play-btn", "n_clicks"),
    State("playing", "datasets"),
    prevent_initial_call=True,
)


# Jahres-Tick: naechstes Jahr, rein clientseitig
app.clientside_callback(
    ClientsideFunction(namespace="map3d", function_name="tick"),
    Output("year-slider", "value"),
    Input("interval", "n_intervals"),
    State("year-slider", "value"),
)

# Karten-Update: Restyle der Hoehen + Labels + Top-10-Panel, clientseitig
app.clientside_callback(
    ClientsideFunction(namespace="map3d", function_name="update"),
    Output("map3d", "figure"),
    Output("year-label", "children"),
    Output("total-label", "children"),
    Input("year-slider", "value"),
    Input("scale-dd", "value"),
    State("store", "datasets"),
)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
