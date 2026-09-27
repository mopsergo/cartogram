/**
 * Kartogramm-Globus mit 3D-Extrusion und adaptiver Dreiecks-
 * subdividierung.
 *
 * Zeigt dieselbe Verformung wie Flach/2.5D – die Kartogramm-Positionen
 * werden über die exakte inverse Equal-Earth-Projektion (equalEarth.ts,
 * gegen pyproj validiert) auf die Kugel zurückgeführt. Da Equal Earth
 * flächentreu ist, bleiben die Kartogramm-Flächenverhältnisse auf der
 * Kugel erhalten.
 *
 * Subdivision (Löcher-Fix): Per-Vertex-Rückprojektion degeneriert bei
 * Dreiecken, deren Ecken alle auf einem Meridian liegen (gerade Wüsten-
 * grenzen, z.B. Algerien/Niger) – ihre Kugelfläche wäre 0, es entstünden
 * Löcher. Riesen-Dreiecke (Küsten mit wenigen Stützpunkten, Δlon > 60°)
 * schneiden auf der Kugel falsch. Der Globus zerlegt solche Dreiecke
 * zur Laufzeit rekursiv über Kanten-Mittelpunkte in der Equal-Earth-
 * Ebene (jeder Mittelpunkt wird exakt rückprojiziert) – bis jede
 * Teilfläche kugeltauglich ist. Reine Renderer-Logik, keine neuen
 * Artefakte.
 *
 * Höhe (2.5D-Optionen): Deckflächen je Entität entlang des Kugelradius
 * angehoben, Seitenwände auf allen Ringsegmenten. geoBlend (Taste G)
 * blendet weich zur unverzerrten Original-Kugel.
 */
import * as THREE from "three";
import { Artifacts } from "../data/types";
import { FrameUpdate, PickResult } from "./shared";
import { equalEarthInverse } from "./equalEarth";

const GLOBE_RADIUS = 1;
/** Visuelle Höhenskala: Anteil der Kugelradien bei vollem Ausschlag */
const GLOBE_H_SCALE = 2.0;
/** Epsilon-Schrumpfung der Seitenwände Richtung Ringzentroid –
 *  geteilte Grenzen liegen in BEIDEN Nachbarringen (zwei Wände an
 *  derselben Stelle!); ohne Schrumpfung z-fighten die Farben. */
const WALL_SHRINK = 4e-3;

/** Wandsegment mit Ring-Vertices für die Zentroid-Schrumpfung. */
interface WallSeg {
  entity: number;
  v0: number;
  v1: number;
  ids: Uint32Array;
}

/** Maximale Subdivisionstiefe (worst case 100°-Bögen, s. QA) */
const MAX_SPLIT_DEPTH = 5;
/** Maximale Sehnenlänge² auf der Einheitskugel (~5,9° Bogen).
 *  Längere Sehnen tauchten mit ihrem Zentrum unter die Ozean-Kugel
 *  (0,996·R) und ließen Ozean/Hintergrund „mitten im Land“ durch-
 *  scheinen; die Sagitta bei 5,9° beträgt 0,13% – sicher über der
 *  0,4%-Lücke zur Ozeankugel. */
const MAX_CHORD2 = 0.104 * 0.104;
/** Puffergröße der dynamischen Deckflächen (Worst case v2/1901:
 *  ~120k Render-Dreiecke, offline vermessen) */
const MAX_RENDER_TRIS = 160000;
/** Liniengrenzen: maximale Segmenttiefe (2^6 = 64 Teilstücke) */
const MAX_LINE_DEPTH = 6;
/** Puffergröße der Grenzlinien-Punkte (Paare; Worst case ~240k) */
const MAX_LINE_PTS = 300000;
/** Grenzlinien schweben diesen Anteil über der Deckfläche (gegen
 *  Z-Fighting mit den Dreiecks-Sehnen, deren Sagitta bis ~0.0013
 *  unter der Kugel liegt) */
const LINE_EPS = 0.003;

export class ReferenceGlobe {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private art: Artifacts;
  private topMesh!: THREE.Mesh;
  private sidesMesh!: THREE.Mesh;
  /** Wandsegmente inkl. Ring-Vertices (Zentroid-Schrumpfung) */
  private wallSegs: WallSeg[];

  // --- Render-Topologie (subdividierte Dreiecke) ---------------------
  /** Punkt-Quellen: [vid] oder [parentIdA, parentIdB] (Mittelpunkt) */
  // --- Laufzeit-Topologie (adaptive Deckflächen-Subdivision) -------
  /** Einheitskugel-Position je kanonischem Vertex (pro Frame) */
  private vertXyz: Float32Array;
  /** (geblendete) lonlat je kanonischem Vertex (pro Frame) */
  private vertLonlat: Float32Array;
  /** Dynamische Render-Dreiecke -> Original-Dreieck (Pick/Entität) */
  private dynTriOrig: Uint32Array;
  /** Höchster je geschriebener Dreieckstand (Tail-Reset) */
  private dynHigh = 0;
  /** Ländergrenzen: dünne schwarze Linien auf der Kugel */
  private linesMesh!: THREE.LineSegments;

  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();
  private spherical = {
    // Startansicht: Europa/Afrika (Länge ~10°O, Breite ~25°N)
    theta: Math.PI / 2 + 0.17, phi: 1.14, radius: 3.4,
  };
  private target = new THREE.Vector3(0, 0, 0);
  private maxPolar = 2.9;

  /** Höhenanteile je Entität, auf den Kugelradius skaliert */
  private entityH: Float32Array;
  private worldWidth: number;

  constructor(art: Artifacts, domElement: HTMLElement) {
    this.art = art;
    const nV = art.manifest.dimensions.num_vertices;
    const nE = art.manifest.dimensions.num_entities;
    // Wandsegmente direkt aus den Ringen – inklusive Ring-Vertices
    // für die Epsilon-Schrumpfung (geteilte Grenzen = zwei Wände!)
    this.wallSegs = [];
    for (const ring of art.rings) {
      const ids = ring.vertexIds;
      for (let i = 0; i < ids.length; i++) {
        this.wallSegs.push({
          entity: ring.entity,
          v0: ids[i],
          v1: ids[(i + 1) % ids.length],
          ids,
        });
      }
    }
    this.scene.background = new THREE.Color(0x0d1117);

    let minX = Infinity, maxX = -Infinity;
    for (let i = 0; i < nV; i++) {
      const x = art.positionsOriginal[i * 2];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
    }
    this.worldWidth = maxX - minX;

    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);

    // Ozean (Material ohne Beleuchtung, konstant dunkel)
    const ocean = new THREE.Mesh(
      new THREE.SphereGeometry(GLOBE_RADIUS * 0.996, 96, 64),
      new THREE.MeshBasicMaterial({ color: 0x16222f }));
    this.scene.add(ocean);

    // --- Render-Topologie: adaptiv pro Frame (siehe updateFrame) ---
    const nV2 = nV;
    this.vertLonlat = new Float32Array(nV2 * 2);
    this.vertXyz = new Float32Array(nV2 * 3);
    this.dynTriOrig = new Uint32Array(MAX_RENDER_TRIS);
    this.entityH = new Float32Array(nE);

    // Debug-/QA-Kanal (DOM-lesbar aus jeder JS-Welt)
    const ds = document.documentElement.dataset;
    ds.globeRenderTris = "0";
    ds.globeDegenLeft = "0";

    // Länder-Deckflächen: dynamischer Puffer, Größe via drawRange
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(MAX_RENDER_TRIS * 9), 3));
    geom.setAttribute("color", new THREE.BufferAttribute(
      new Float32Array(MAX_RENDER_TRIS * 9), 3));
    // Feste bounding sphere (Kugel herrscht immer im Blick) – kein
    // teures computeBoundingSphere über den Großpuffer pro Frame
    geom.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 2);
    this.topMesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide }));
    this.scene.add(this.topMesh);

    // Seitenwände: 2 Dreiecke je Ringsegment (Non-Indexed)
    const sideGeom = new THREE.BufferGeometry();
    sideGeom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(this.wallSegs.length * 6 * 3), 3));
    sideGeom.setAttribute("color", new THREE.BufferAttribute(
      new Float32Array(this.wallSegs.length * 6 * 3), 3));
    this.sidesMesh = new THREE.Mesh(sideGeom, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide }));
    this.scene.add(this.sidesMesh);

    // Graticule (30°) – geografische Orientierung auf der Original-Kugel
    const graticule = new THREE.LineSegments(
      this.buildGraticule(),
      new THREE.LineBasicMaterial({
        color: 0x2c3a4e, transparent: true, opacity: 0.5 }));
    this.scene.add(graticule);

    // Ländergrenzen: dünne schwarze Linien, dynamisch pro Frame
    // (geodätisch unterteilt, siehe updateFrame)
    const lineGeom = new THREE.BufferGeometry();
    lineGeom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(MAX_LINE_PTS * 3), 3));
    lineGeom.boundingSphere = new THREE.Sphere(
      new THREE.Vector3(0, 0, 0), 2);
    lineGeom.setDrawRange(0, 0);
    this.linesMesh = new THREE.LineSegments(lineGeom,
      new THREE.LineBasicMaterial({ color: 0x000000 }));
    this.scene.add(this.linesMesh);

    this.attachControls(domElement);
    this.applyCamera();
  }

  // ----------------------------------------------------------- Frame

  private static toSphereOut(lonDeg: number, latDeg: number,
                             out: Float32Array, off: number,
                             radius: number): void {
    const lon = lonDeg * Math.PI / 180;
    const lat = latDeg * Math.PI / 180;
    const c = Math.cos(lat);
    out[off] = c * Math.cos(lon) * radius;
    out[off + 1] = Math.sin(lat) * radius;
    out[off + 2] = -c * Math.sin(lon) * radius;
  }

  updateFrame(update: FrameUpdate): void {
    const art = this.art;
    const nE = art.manifest.dimensions.num_entities;
    const geoBlend = update.geoBlend ?? 0;
    const xyFrame = update.vertexXY;
    const nV = art.manifest.dimensions.num_vertices;
    const nT = art.manifest.dimensions.num_triangles;
    const pll = this.vertLonlat;
    const vx = this.vertXyz;
    const inv: [number, number] = [0, 0];

    // 1) Lonlat je kanonischem Vertex: inverse EE (Kartogramm),
    //    Blend mit Original-Geografie (Taste G)
    if (geoBlend >= 0.999) {
      pll.set(art.lonlat);
    } else {
      const q = geoBlend;
      for (let v = 0; v < nV; v++) {
        equalEarthInverse(xyFrame[v * 2], xyFrame[v * 2 + 1], inv);
        if (q <= 0.001) {
          pll[v * 2] = inv[0];
          pll[v * 2 + 1] = inv[1];
        } else {
          pll[v * 2] = inv[0] * (1 - q) + art.lonlat[v * 2] * q;
          pll[v * 2 + 1] = inv[1] * (1 - q)
            + art.lonlat[v * 2 + 1] * q;
        }
      }
    }

    // 2) Einheitskugel-Position je kanonischem Vertex
    for (let v = 0; v < nV; v++) {
      ReferenceGlobe.toSphereOut(pll[v * 2], pll[v * 2 + 1],
        vx, v * 3, 1);
    }

    // 3) Höhen: Plane-Meter -> Anteil des Kugelradius
    const heights = update.heights;
    let anyHeight = false;
    for (let e = 0; e < nE; e++) {
      const h = heights ? heights[e] : 0;
      const hr = h > 0 ? (h / this.worldWidth) * GLOBE_H_SCALE : 0;
      this.entityH[e] = hr;
      if (hr > 0) anyHeight = true;
    }

    // 4) Deckflächen: adaptive Laufzeit-Subdivision auf der Kugel.
    //    Extrem gestreckte Dreiecke (Kartogramm!) spannen Bögen von
    //    10–100°; ihre flachen Sehnen tauchten unter die Ozean-Kugel
    //    (0,996·R) und ließen Ozean/Hintergrund „mitten im Land“
    //    durchscheinen. Deshalb wird JE FRAME nach aktueller Bogen-
    //    länge unterteilt – Mittelpunkte direkt auf der Kugel
    //    (normalisierte Summe, keine Rückprojektion nötig).
    const pos = (this.topMesh.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    const colorAttr = this.topMesh.geometry.attributes
      .color as THREE.BufferAttribute;
    const colors = colorAttr.array as Float32Array;
    const triOrig = this.dynTriOrig;
    let count = 0;
    let overflow = 0;
    const emit = (x1: number, y1: number, z1: number,
                   x2: number, y2: number, z2: number,
                   x3: number, y3: number, z3: number,
                   rad: number, cr: number, cg: number, cb: number,
                   orig: number): void => {
      if (count >= MAX_RENDER_TRIS) { overflow++; return; }
      let o = count * 9;
      pos[o] = x1 * rad; pos[o + 1] = y1 * rad; pos[o + 2] = z1 * rad;
      pos[o + 3] = x2 * rad; pos[o + 4] = y2 * rad; pos[o + 5] = z2 * rad;
      pos[o + 6] = x3 * rad; pos[o + 7] = y3 * rad; pos[o + 8] = z3 * rad;
      colors[o] = cr; colors[o + 1] = cg; colors[o + 2] = cb;
      colors[o + 3] = cr; colors[o + 4] = cg; colors[o + 5] = cb;
      colors[o + 6] = cr; colors[o + 7] = cg; colors[o + 8] = cb;
      triOrig[count] = orig;
      count++;
    };
    const subdivide = (x1: number, y1: number, z1: number,
                       x2: number, y2: number, z2: number,
                       x3: number, y3: number, z3: number,
                       depth: number, orig: number, rad: number,
                       cr: number, cg: number, cb: number): void => {
      const ax = x2 - x1, ay = y2 - y1, az = z2 - z1;
      const bx = x3 - x2, by = y3 - y2, bz = z3 - z2;
      const cx = x1 - x3, cy = y1 - y3, cz = z1 - z3;
      const l12 = ax * ax + ay * ay + az * az;
      const l23 = bx * bx + by * by + bz * bz;
      const l31 = cx * cx + cy * cy + cz * cz;
      if (depth >= MAX_SPLIT_DEPTH
          || (l12 <= MAX_CHORD2 && l23 <= MAX_CHORD2
            && l31 <= MAX_CHORD2)) {
        emit(x1, y1, z1, x2, y2, z2, x3, y3, z3,
          rad, cr, cg, cb, orig);
        return;
      }
      // Mittelpunkte auf der Kugel (normalisierte Summen)
      let mx = x1 + x2, my = y1 + y2, mz = z1 + z2;
      let n = 1 / Math.sqrt(mx * mx + my * my + mz * mz);
      mx *= n; my *= n; mz *= n;
      let nx = x2 + x3, ny = y2 + y3, nz = z2 + z3;
      n = 1 / Math.sqrt(nx * nx + ny * ny + nz * nz);
      nx *= n; ny *= n; nz *= n;
      let px = x3 + x1, py = y3 + y1, pz = z3 + z1;
      n = 1 / Math.sqrt(px * px + py * py + pz * pz);
      px *= n; py *= n; pz *= n;
      subdivide(x1, y1, z1, mx, my, mz, px, py, pz,
        depth + 1, orig, rad, cr, cg, cb);
      subdivide(mx, my, mz, x2, y2, z2, nx, ny, nz,
        depth + 1, orig, rad, cr, cg, cb);
      subdivide(px, py, pz, nx, ny, nz, x3, y3, z3,
        depth + 1, orig, rad, cr, cg, cb);
      subdivide(mx, my, mz, nx, ny, nz, px, py, pz,
        depth + 1, orig, rad, cr, cg, cb);
    };
    for (let t = 0; t < nT; t++) {
      const e = art.triangleEntity[t];
      const rad = GLOBE_RADIUS + this.entityH[e];
      const cr = update.entityColors[e * 3];
      const cg = update.entityColors[e * 3 + 1];
      const cb = update.entityColors[e * 3 + 2];
      const a = art.expandMap[t * 3] * 3;
      const b = art.expandMap[t * 3 + 1] * 3;
      const c = art.expandMap[t * 3 + 2] * 3;
      subdivide(vx[a], vx[a + 1], vx[a + 2],
        vx[b], vx[b + 1], vx[b + 2],
        vx[c], vx[c + 1], vx[c + 2],
        0, t, rad, cr, cg, cb);
    }
    // Ungenutzter Tail degenerieren (Pick-Sicherheit) + drawRange
    const high = this.dynHigh;
    if (count < high) {
      for (let i = count * 9; i < high * 9; i++) pos[i] = 0;
    }
    this.dynHigh = Math.max(high, count);
    this.topMesh.geometry.setDrawRange(0, count * 3);
    const posAttr = this.topMesh.geometry.attributes
      .position as THREE.BufferAttribute;
    posAttr.clearUpdateRanges();
    posAttr.addUpdateRange(0, Math.max(count, 1) * 9);
    posAttr.needsUpdate = true;
    colorAttr.clearUpdateRanges();
    colorAttr.addUpdateRange(0, Math.max(count, 1) * 9);
    colorAttr.needsUpdate = true;

    // 5) Seitenwände auf den Ringsegmenten (Küsten + Grenzen)
    const sidePos = (this.sidesMesh.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    const sideCol = (this.sidesMesh.geometry.attributes
      .color as THREE.BufferAttribute).array as Float32Array;
    let sp = 0;
    if (anyHeight) {
      for (const seg of this.wallSegs) {
        const h = this.entityH[seg.entity];
        if (h <= 0) continue;
        const rTop = GLOBE_RADIUS + h;
        // Blockfarbe = Deckflächenfarbe (Benutzeranforderung: der
        // ganze Block in der Farbe der Fläche)
        const rC = update.entityColors[seg.entity * 3];
        const gC = update.entityColors[seg.entity * 3 + 1];
        const bC = update.entityColors[seg.entity * 3 + 2];
        // Ring-Zentroid der aktuellen Positionen, dann Epsilon-
        // Schrumpfung: geteilte Grenzen liegen in beiden Nachbar-
        // ringen (zwei Wände an derselben Stelle) – die Schrumpfung
        // zieht jede Wand in ihr eigenes Land, kein Z-Fighting und
        // jede Wand zeigt verlässlich ihre eigene Entitätsfarbe.
        let cx = 0, cy = 0;
        const ids = seg.ids;
        for (let k = 0; k < ids.length; k++) {
          cx += pll[ids[k] * 2];
          cy += pll[ids[k] * 2 + 1];
        }
        cx /= ids.length;
        cy /= ids.length;
        const lon0 = pll[seg.v0 * 2] + (cx - pll[seg.v0 * 2]) * WALL_SHRINK;
        const lat0 = pll[seg.v0 * 2 + 1]
          + (cy - pll[seg.v0 * 2 + 1]) * WALL_SHRINK;
        const lon1 = pll[seg.v1 * 2] + (cx - pll[seg.v1 * 2]) * WALL_SHRINK;
        const lat1 = pll[seg.v1 * 2 + 1]
          + (cy - pll[seg.v1 * 2 + 1]) * WALL_SHRINK;
        ReferenceGlobe.toSphereOut(lon0, lat0, sidePos, sp,
          GLOBE_RADIUS);
        ReferenceGlobe.toSphereOut(lon1, lat1, sidePos, sp + 3,
          GLOBE_RADIUS);
        ReferenceGlobe.toSphereOut(lon1, lat1, sidePos, sp + 6, rTop);
        ReferenceGlobe.toSphereOut(lon0, lat0, sidePos, sp + 9,
          GLOBE_RADIUS);
        ReferenceGlobe.toSphereOut(lon1, lat1, sidePos, sp + 12, rTop);
        ReferenceGlobe.toSphereOut(lon0, lat0, sidePos, sp + 15, rTop);
        for (let i = 0; i < 6; i++) {
          sideCol[(sp / 3) + i * 3] = rC;
          sideCol[(sp / 3) + i * 3 + 1] = gC;
          sideCol[(sp / 3) + i * 3 + 2] = bC;
        }
        sp += 18;
      }
    }
    for (let i = sp; i < sidePos.length; i++) sidePos[i] = 0;
    for (let i = (sp / 3); i < sideCol.length; i++) sideCol[i] = 0;
    (this.sidesMesh.geometry.attributes
      .position as THREE.BufferAttribute).needsUpdate = true;
    (this.sidesMesh.geometry.attributes
      .color as THREE.BufferAttribute).needsUpdate = true;
    this.sidesMesh.geometry.computeBoundingSphere();

    // 6) Ländergrenzen: dünne schwarze Linien auf der Kugeloberfläche.
    //    Ringsegmente (Küsten + Binnengrenzen) geodätisch unterteilt –
    //    lange Grenzen als gerade Sehnen tauchten sonst wie früher
    //    die Deckflächen unter die Ozean-Kugel und würden mittendrin
    //    unsichtbar. Mittelpunkte direkt auf der Kugel (normalisierte
    //    Summe), Radius = Deckfläche + LINE_EPS gegen Z-Fighting.
    const lpos = (this.linesMesh.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    let lc = 0;
    let lOverflow = 0;
    const emitPair = (x1: number, y1: number, z1: number,
                      x2: number, y2: number, z2: number,
                      r: number): void => {
      if (lc + 2 > MAX_LINE_PTS) { lOverflow++; return; }
      const o = lc * 3;
      lpos[o] = x1 * r; lpos[o + 1] = y1 * r; lpos[o + 2] = z1 * r;
      lpos[o + 3] = x2 * r; lpos[o + 4] = y2 * r; lpos[o + 5] = z2 * r;
      lc += 2;
    };
    const subdivideLine = (x1: number, y1: number, z1: number,
                           x2: number, y2: number, z2: number,
                           r: number, depth: number): void => {
      const dx = x2 - x1, dy = y2 - y1, dz = z2 - z1;
      if (depth >= MAX_LINE_DEPTH
          || dx * dx + dy * dy + dz * dz <= MAX_CHORD2) {
        emitPair(x1, y1, z1, x2, y2, z2, r);
        return;
      }
      let mx = x1 + x2, my = y1 + y2, mz = z1 + z2;
      const n = 1 / Math.sqrt(mx * mx + my * my + mz * mz);
      mx *= n; my *= n; mz *= n;
      subdivideLine(x1, y1, z1, mx, my, mz, r, depth + 1);
      subdivideLine(mx, my, mz, x2, y2, z2, r, depth + 1);
    };
    for (const seg of this.wallSegs) {
      const r = GLOBE_RADIUS + this.entityH[seg.entity] + LINE_EPS;
      const a = seg.v0 * 3, b = seg.v1 * 3;
      subdivideLine(vx[a], vx[a + 1], vx[a + 2],
        vx[b], vx[b + 1], vx[b + 2], r, 0);
    }
    this.linesMesh.geometry.setDrawRange(0, lc);
    const lineAttr = this.linesMesh.geometry.attributes
      .position as THREE.BufferAttribute;
    lineAttr.clearUpdateRanges();
    lineAttr.addUpdateRange(0, Math.max(lc, 1) * 3);
    lineAttr.needsUpdate = true;

    // QA-Kanal nur bei Änderung schreiben (kein DOM-Churn pro Frame)
    const ds = document.documentElement.dataset;
    const cnt = String(count);
    if (ds.globeRenderTris !== cnt) ds.globeRenderTris = cnt;
    const ofl = String(overflow);
    if (ds.globeDegenLeft !== ofl) ds.globeDegenLeft = ofl;
    const lpts = String(lc);
    if (ds.globeLinePts !== lpts) ds.globeLinePts = lpts;
    const lofl = String(lOverflow);
    if (ds.globeLineOverflow !== lofl) ds.globeLineOverflow = lofl;
  }

  applyCamera(): void {
    const phi = Math.min(Math.max(this.spherical.phi, 0.15), this.maxPolar);
    const { theta, radius } = this.spherical;
    this.camera.position.set(
      radius * Math.sin(phi) * Math.sin(theta),
      radius * Math.cos(phi),
      radius * Math.sin(phi) * Math.cos(theta));
    this.camera.lookAt(this.target);
  }

  resize(width: number, height: number): void {
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  resetCamera(): void {
    this.spherical = {
      theta: Math.PI / 2 + 0.17, phi: 1.14, radius: 3.4 };
    this.target.set(0, 0, 0);
    this.applyCamera();
  }

  pick(clientX: number, clientY: number, width: number,
       height: number): PickResult | null {
    this.mouse.x = (clientX / width) * 2 - 1;
    this.mouse.y = -(clientY / height) * 2 + 1;
    this.raycaster.setFromCamera(this.mouse, this.camera);
    const hits = this.raycaster.intersectObject(this.topMesh, false);
    if (hits.length === 0) return null;
    const orig = this.dynTriOrig[hits[0].faceIndex!];
    return {
      entity: this.art.triangleEntity[orig],
      triangle: orig,
    };
  }

  private buildGraticule(): THREE.BufferGeometry {
    const pts: number[] = [];
    const xyz = (lon: number, lat: number, r: number) => {
      const lo = lon * Math.PI / 180, la = lat * Math.PI / 180;
      const c = Math.cos(la);
      pts.push(c * Math.cos(lo) * r, Math.sin(la) * r,
               -c * Math.sin(lo) * r);
    };
    const R = GLOBE_RADIUS * 1.002;
    for (let lat = -60; lat <= 60; lat += 30) {
      for (let lon = -180; lon < 180; lon += 3) {
        xyz(lon, lat, R); xyz(lon + 3, lat, R);
      }
    }
    for (let lon = -180; lon < 180; lon += 30) {
      for (let lat = -85; lat < 85; lat += 3) {
        xyz(lon, lat, R); xyz(lon, lat + 3, R);
      }
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(pts), 3));
    return geom;
  }

  private attachControls(dom: HTMLElement): void {
    let rotating = false;
    let lastX = 0, lastY = 0;
    dom.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      rotating = true;
      lastX = e.clientX;
      lastY = e.clientY;
      dom.setPointerCapture(e.pointerId);
    });
    dom.addEventListener("pointermove", (e) => {
      if (!rotating) return;
      this.spherical.theta -= (e.clientX - lastX) * 0.005;
      this.spherical.phi -= (e.clientY - lastY) * 0.005;
      lastX = e.clientX;
      lastY = e.clientY;
    });
    dom.addEventListener("pointerup", () => { rotating = false; });
    dom.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.spherical.radius *= Math.exp(e.deltaY * 0.0011);
      this.spherical.radius = Math.min(Math.max(
        this.spherical.radius, 1.25), 12);
    }, { passive: false });
  }
}
