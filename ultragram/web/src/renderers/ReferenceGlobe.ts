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

/** Ab hier werden Dreiecke subdividiert */
const MAX_LON_SPAN_DEG = 60;
/** Kugel-Kreuzprodukt-Norm darunter = degeneriert (Loch-Gefahr) */
const DEGEN_NRM = 1e-9;
const MAX_SPLIT_DEPTH = 4;

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
  private pointA: Int32Array;
  private pointB: Int32Array;
  private numPoints: number;
  /** Render-Dreiecke: 3 Punkt-IDs je Dreieck */
  private renderTris: Uint32Array;
  /** Render-Dreieck -> Original-Dreieck (Pick, Entität, Ringname) */
  private renderTriOrig: Uint32Array;
  private numRenderTris: number;
  /** Original-Lonlat je Punkt (für geoBlend + Mittelpunkte) */
  private pointOrigLonlat: Float32Array;

  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();
  private spherical = {
    // Startansicht: Europa/Afrika (Länge ~10°O, Breite ~25°N)
    theta: Math.PI / 2 + 0.17, phi: 1.14, radius: 3.4,
  };
  private target = new THREE.Vector3(0, 0, 0);
  private maxPolar = 2.9;

  /** Aktuelle xy je Punkt (kanonisch + Mittelpunkte) */
  private pointXY: Float32Array;
  /** Aktuelle (geblendete) lonlat je Punkt */
  private pointLonlat: Float32Array;
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

    // --- Render-Topologie aufbauen (einmalig, statisch)
    const topo = this.buildRenderTopology();
    this.pointA = topo.pointA;
    this.pointB = topo.pointB;
    this.numPoints = topo.numPoints;
    this.renderTris = topo.renderTris;
    this.renderTriOrig = topo.renderTriOrig;
    this.numRenderTris = topo.numRenderTris;
    this.pointOrigLonlat = topo.pointOrigLonlat;
    this.pointXY = new Float32Array(topo.numPoints * 2);
    this.pointLonlat = new Float32Array(topo.numPoints * 2);
    this.entityH = new Float32Array(nE);

    // Debug-/QA-Kanal (DOM-lesbar aus jeder JS-Welt)
    const ds = document.documentElement.dataset;
    ds.globeRenderTris = String(topo.numRenderTris);
    ds.globeDegenLeft = String(topo.degenerateLeft);

    // Länder-Deckflächen: subdividierte Topologie auf die Kugel.
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(this.numRenderTris * 3 * 3), 3));
    geom.setAttribute("color", new THREE.BufferAttribute(
      new Float32Array(this.numRenderTris * 3 * 3), 3));
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

    this.attachControls(domElement);
    this.applyCamera();
  }

  // ------------------------------------------------ Render-Topologie

  private buildRenderTopology() {
    const art = this.art;
    const nV = art.manifest.dimensions.num_vertices;
    const nT = art.manifest.dimensions.num_triangles;

    // Punkte 0..nV-1 = kanonische Vertices; danach Mittelpunkte.
    const pointA: number[] = [];
    const pointB: number[] = [];
    const origLon: number[] = [];
    const origLat: number[] = [];
    for (let v = 0; v < nV; v++) {
      pointA.push(v); pointB.push(-1);
      origLon.push(art.lonlat[v * 2]);
      origLat.push(art.lonlat[v * 2 + 1]);
    }
    const midPoint = (p: number, q: number): number => {
      // Original-lonlat des Mittelpunkts: exakte Rückprojektion des
      // Original-Positions-Mittelpunkts (statisch, einmalig)
      const inv: [number, number] = [0, 0];
      let ax: number, ay: number, bx: number, by: number;
      if (p >= nV) {  // rekursiv: Mittelpunkte von Mittelpunkten
        ax = 0; ay = 0; // wird unten über pointXY nicht gebraucht –
        // Original-Ebene: Eltern-Originale mitteln (rekursiv speichern
        // wir die Original-x/y je Punkt mit):
        ax = this.origXY(pointA, pointB, p, 0);
        ay = this.origXY(pointA, pointB, p, 1);
      } else {
        ax = art.positionsOriginal[p * 2];
        ay = art.positionsOriginal[p * 2 + 1];
      }
      if (q >= nV) {
        bx = this.origXY(pointA, pointB, q, 0);
        by = this.origXY(pointA, pointB, q, 1);
      } else {
        bx = art.positionsOriginal[q * 2];
        by = art.positionsOriginal[q * 2 + 1];
      }
      const id = pointA.length;
      pointA.push(p); pointB.push(q);
      equalEarthInverse(0.5 * (ax + bx), 0.5 * (ay + by), inv);
      origLon.push(inv[0]); origLat.push(inv[1]);
      return id;
    };

    const renderTris: number[] = [];
    const triOrig: number[] = [];

    const toXyz = (lon: number, lat: number,
                   out: [number, number, number]) => {
      const lo = lon * Math.PI / 180, la = lat * Math.PI / 180;
      const c = Math.cos(la);
      out[0] = c * Math.cos(lo);
      out[1] = Math.sin(la);
      out[2] = -c * Math.sin(lo);
    };

    // Kugelgüte eines Dreiecks über drei Punkt-IDs (Original-lonlat)
    const isBad = (pa: number, pb: number, pc: number): boolean => {
      // Kollabierte Dreiecke (identische Vertices nach dem Welding)
      // haben nirgendwo Fläche – sie werden unverändert gezeichnet
      // (unsichtbar) und NICHT subdividiert (das würde sie aufblähen).
      const ax0 = this.origXY(pointA, pointB, pa, 0);
      const ay0 = this.origXY(pointA, pointB, pa, 1);
      const bx0 = this.origXY(pointA, pointB, pb, 0);
      const by0 = this.origXY(pointA, pointB, pb, 1);
      const cx0 = this.origXY(pointA, pointB, pc, 0);
      const cy0 = this.origXY(pointA, pointB, pc, 1);
      const planeArea = Math.abs(
        (bx0 - ax0) * (cy0 - ay0) - (cx0 - ax0) * (by0 - ay0)) / 2;
      if (planeArea < 1e4) return false;   // < ~100 m × 100 m: Sliver
      const l0 = [origLon[pa], origLat[pa]];
      const l1 = [origLon[pb], origLat[pb]];
      const l2 = [origLon[pc], origLat[pc]];
      const dl = Math.max(Math.abs(l0[0] - l1[0]),
        Math.abs(l1[0] - l2[0]), Math.abs(l2[0] - l0[0]));
      if (dl > MAX_LON_SPAN_DEG) return true;
      // Kugel-Kreuzprodukt: degeneriert -> Loch
      const xyz: [number, number, number][] = [[0, 0, 0], [0, 0, 0],
                                                [0, 0, 0]];
      toXyz(l0[0], l0[1], xyz[0]);
      toXyz(l1[0], l1[1], xyz[1]);
      toXyz(l2[0], l2[1], xyz[2]);
      const ax = xyz[1][0] - xyz[0][0], ay = xyz[1][1] - xyz[0][1],
            az = xyz[1][2] - xyz[0][2];
      const bx = xyz[2][0] - xyz[0][0], by = xyz[2][1] - xyz[0][1],
            bz = xyz[2][2] - xyz[0][2];
      const nrm = Math.sqrt(
        (ay * bz - az * by) ** 2 + (az * bx - ax * bz) ** 2
        + (ax * by - ay * bx) ** 2);
      return nrm < DEGEN_NRM;
    };

    const emit = (pa: number, pb: number, pc: number, orig: number) => {
      renderTris.push(pa, pb, pc);
      triOrig.push(orig);
    };

    const subdivide = (pa: number, pb: number, pc: number, orig: number,
                       depth: number) => {
      if (depth >= MAX_SPLIT_DEPTH || !isBad(pa, pb, pc)) {
        emit(pa, pb, pc, orig);
        return;
      }
      const mab = midPoint(pa, pb);
      const mbc = midPoint(pb, pc);
      const mca = midPoint(pc, pa);
      subdivide(pa, mab, mca, orig, depth + 1);
      subdivide(mab, pb, mbc, orig, depth + 1);
      subdivide(mca, mbc, pc, orig, depth + 1);
      subdivide(mab, mbc, mca, orig, depth + 1);
    };

    for (let t = 0; t < nT; t++) {
      subdivide(art.expandMap[t * 3], art.expandMap[t * 3 + 1],
                art.expandMap[t * 3 + 2], t, 0);
    }

    // Rest-Degenerate nach der Subdivision mit echter Plattenfläche
    // (kollabierte Sliver sind beabsichtigt und harmlos; QA-Kanal)
    let degenerateLeft = 0;
    const qxyz: [number, number, number][] = [[0, 0, 0], [0, 0, 0],
                                              [0, 0, 0]];
    for (let t = 0; t < renderTris.length / 3; t++) {
      const ps = [renderTris[t * 3], renderTris[t * 3 + 1],
                  renderTris[t * 3 + 2]];
      const ax0 = this.origXY(pointA, pointB, ps[0], 0);
      const ay0 = this.origXY(pointA, pointB, ps[0], 1);
      const bx0 = this.origXY(pointA, pointB, ps[1], 0);
      const by0 = this.origXY(pointA, pointB, ps[1], 1);
      const cx0 = this.origXY(pointA, pointB, ps[2], 0);
      const cy0 = this.origXY(pointA, pointB, ps[2], 1);
      const planeArea = Math.abs(
        (bx0 - ax0) * (cy0 - ay0) - (cx0 - ax0) * (by0 - ay0)) / 2;
      if (planeArea < 1e4) continue;
      for (let k = 0; k < 3; k++) {
        toXyz(origLon[ps[k]], origLat[ps[k]], qxyz[k]);
      }
      const ax = qxyz[1][0] - qxyz[0][0], ay = qxyz[1][1] - qxyz[0][1],
            az = qxyz[1][2] - qxyz[0][2];
      const bx = qxyz[2][0] - qxyz[0][0], by = qxyz[2][1] - qxyz[0][1],
            bz = qxyz[2][2] - qxyz[0][2];
      const nrm = Math.sqrt(
        (ay * bz - az * by) ** 2 + (az * bx - ax * bz) ** 2
        + (ax * by - ay * bx) ** 2);
      if (nrm < DEGEN_NRM) degenerateLeft++;
    }

    return {
      pointA: new Int32Array(pointA),
      pointB: new Int32Array(pointB),
      numPoints: pointA.length,
      renderTris: new Uint32Array(renderTris),
      renderTriOrig: new Uint32Array(triOrig),
      numRenderTris: renderTris.length / 3,
      pointOrigLonlat: new Float32Array(
        origLon.flatMap((lo, i) => [lo, origLat[i]])),
      degenerateLeft,
    };
  }

  /** Original-Position (x/y-Komponente comp) eines Punkts rekursiv. */
  private origXY(A: number[], B: number[], p: number, comp: number): number {
    if (B[p] < 0) {
      return this.art.positionsOriginal[A[p] * 2 + comp];
    }
    return 0.5 * (this.origXY(A, B, A[p], comp)
                + this.origXY(A, B, B[p], comp));
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
    const nP = this.numPoints;
    const A = this.pointA, B = this.pointB;
    const pxy = this.pointXY;
    const pll = this.pointLonlat;
    const inv: [number, number] = [0, 0];

    // 1) Aktuelle xy je Punkt (Mittelpunkte rekursiv, in ID-Reihenfolge
    //    sind Eltern immer vor Kindern definiert)
    const nV = art.manifest.dimensions.num_vertices;
    for (let p = 0; p < nV; p++) {
      pxy[p * 2] = xyFrame[p * 2];
      pxy[p * 2 + 1] = xyFrame[p * 2 + 1];
    }
    for (let p = nV; p < nP; p++) {
      const a = A[p] * 2, b = B[p] * 2;
      pxy[p * 2] = 0.5 * (pxy[a] + pxy[b]);
      pxy[p * 2 + 1] = 0.5 * (pxy[a + 1] + pxy[b + 1]);
    }

    // 2) Lonlat je Punkt: inverse EE (Kartogramm), Blend mit Original
    if (geoBlend >= 0.999) {
      pll.set(this.pointOrigLonlat);
    } else {
      for (let p = 0; p < nP; p++) {
        equalEarthInverse(pxy[p * 2], pxy[p * 2 + 1], inv);
        if (geoBlend <= 0.001) {
          pll[p * 2] = inv[0];
          pll[p * 2 + 1] = inv[1];
        } else {
          const q = geoBlend;
          pll[p * 2] = inv[0] * (1 - q) + this.pointOrigLonlat[p * 2] * q;
          pll[p * 2 + 1] = inv[1] * (1 - q)
            + this.pointOrigLonlat[p * 2 + 1] * q;
        }
      }
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

    // 4) Deckflächen: Render-Dreiecke auf die Kugel
    const pos = (this.topMesh.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    const colorAttr = this.topMesh.geometry.attributes
      .color as THREE.BufferAttribute;
    const colors = colorAttr.array as Float32Array;
    const rt = this.renderTris;
    for (let t = 0; t < this.numRenderTris; t++) {
      const orig = this.renderTriOrig[t];
      const e = art.triangleEntity[orig];
      const r = update.entityColors[e * 3];
      const g = update.entityColors[e * 3 + 1];
      const b = update.entityColors[e * 3 + 2];
      const rad = GLOBE_RADIUS + this.entityH[e];
      for (let k = 0; k < 3; k++) {
        const p = rt[t * 3 + k];
        const s = t * 3 + k;
        ReferenceGlobe.toSphereOut(pll[p * 2], pll[p * 2 + 1],
          pos, s * 3, rad);
        colors[s * 3] = r;
        colors[s * 3 + 1] = g;
        colors[s * 3 + 2] = b;
      }
    }
    (this.topMesh.geometry.attributes
      .position as THREE.BufferAttribute).needsUpdate = true;
    colorAttr.needsUpdate = true;
    this.topMesh.geometry.computeBoundingSphere();

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
    const orig = this.renderTriOrig[hits[0].faceIndex!];
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
