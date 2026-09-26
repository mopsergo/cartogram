/**
 * Reference Globe (Plan §7.4): statische, unverzerrte Ländergeometrien
 * auf einer Kugel, Farbe nach derselben aktiven Kennzahl, gleiche
 * Timeline und Auswahl; frei drehbar und zoombar; keine Extrusion.
 */
import * as THREE from "three";
import { Artifacts } from "../data/types";
import { FrameUpdate } from "./shared";

const GLOBE_RADIUS = 1;

export class ReferenceGlobe {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private art: Artifacts;
  private countryMesh!: THREE.Mesh;
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();
  private spherical = {
    // Startansicht: Europa/Afrika (Länge ~10°O, Breite ~25°N)
    theta: Math.PI / 2 + 0.17, phi: 1.14, radius: 3.4,
  };
  private target = new THREE.Vector3(0, 0, 0);
  private maxPolar = 2.9;

  constructor(art: Artifacts, domElement: HTMLElement) {
    this.art = art;
    this.scene.background = new THREE.Color(0x0d1117);

    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);

    // Ozean (Material ohne Beleuchtung, konstant dunkel)
    const ocean = new THREE.Mesh(
      new THREE.SphereGeometry(GLOBE_RADIUS * 0.996, 96, 64),
      new THREE.MeshBasicMaterial({ color: 0x16222f }));
    this.scene.add(ocean);

    // Länder: kanonische Topologie auf die Kugel projiziert.
    // MeshBasicMaterial (ohne Licht-Dimmung): die Farbskala bleibt
    // ungefiltert sichtbar – auch die zeitliche Änderung der Farben.
    const nT = art.manifest.dimensions.num_triangles;
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(nT * 3 * 3), 3));
    geom.setAttribute("color", new THREE.BufferAttribute(
      new Float32Array(nT * 3 * 3), 3));
    this.countryMesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide }));
    this.scene.add(this.countryMesh);

    this.fillStaticPositions();

    // Graticule (30°)
    const graticule = new THREE.LineSegments(
      this.buildGraticule(),
      new THREE.LineBasicMaterial({
        color: 0x2c3a4e, transparent: true, opacity: 0.5 }));
    this.scene.add(graticule);

    // Licht: MeshBasicMaterial braucht keine Beleuchtung – die
    // Farbskala bleibt ungefiltert (siehe oben).

    this.attachControls(domElement);
    this.applyCamera();
  }

  /** Länge/Breite -> Kugelposition (statisch, unverzerrt). */
  private static toSphere(lonDeg: number, latDeg: number,
                          out: [number, number, number]): void {
    const lon = lonDeg * Math.PI / 180;
    const lat = latDeg * Math.PI / 180;
    const c = Math.cos(lat);
    out[0] = c * Math.cos(lon);
    out[1] = Math.sin(lat);
    out[2] = -c * Math.sin(lon);
  }

  private fillStaticPositions(): void {
    const art = this.art;
    const nT = art.manifest.dimensions.num_triangles;
    const pos = (this.countryMesh.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    const xyz: [number, number, number] = [0, 0, 0];
    for (let s = 0; s < nT * 3; s++) {
      const v = art.expandMap[s];
      ReferenceGlobe.toSphere(
        art.lonlat[v * 2], art.lonlat[v * 2 + 1], xyz);
      pos[s * 3] = xyz[0] * GLOBE_RADIUS;
      pos[s * 3 + 1] = xyz[1] * GLOBE_RADIUS;
      pos[s * 3 + 2] = xyz[2] * GLOBE_RADIUS;
    }
    (this.countryMesh.geometry.attributes
      .position as THREE.BufferAttribute).needsUpdate = true;
    this.countryMesh.geometry.computeBoundingSphere();
  }

  private buildGraticule(): THREE.BufferGeometry {
    const pts: number[] = [];
    const xyz: [number, number, number] = [0, 0, 0];
    const R = GLOBE_RADIUS * 1.002;
    for (let lat = -60; lat <= 60; lat += 30) {
      for (let lon = -180; lon < 180; lon += 3) {
        ReferenceGlobe.toSphere(lon, lat, xyz);
        pts.push(xyz[0] * R, xyz[1] * R, xyz[2] * R);
        ReferenceGlobe.toSphere(lon + 3, lat, xyz);
        pts.push(xyz[0] * R, xyz[1] * R, xyz[2] * R);
      }
    }
    for (let lon = -180; lon < 180; lon += 30) {
      for (let lat = -85; lat < 85; lat += 3) {
        ReferenceGlobe.toSphere(lon, lat, xyz);
        pts.push(xyz[0] * R, xyz[1] * R, xyz[2] * R);
        ReferenceGlobe.toSphere(lon, lat + 3, xyz);
        pts.push(xyz[0] * R, xyz[1] * R, xyz[2] * R);
      }
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(pts), 3));
    return geom;
  }

  updateFrame(update: FrameUpdate): void {
    const art = this.art;
    const nT = art.manifest.dimensions.num_triangles;
    const colorAttr = this.countryMesh.geometry.attributes
      .color as THREE.BufferAttribute;
    const colors = colorAttr.array as Float32Array;
    for (let t = 0; t < nT; t++) {
      const e = art.triangleEntity[t];
      const r = update.entityColors[e * 3];
      const g = update.entityColors[e * 3 + 1];
      const b = update.entityColors[e * 3 + 2];
      for (let k = 0; k < 3; k++) {
        colors[(t * 3 + k) * 3] = r;
        colors[(t * 3 + k) * 3 + 1] = g;
        colors[(t * 3 + k) * 3 + 2] = b;
      }
    }
    colorAttr.needsUpdate = true;
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
       height: number): number | null {
    this.mouse.x = (clientX / width) * 2 - 1;
    this.mouse.y = -(clientY / height) * 2 + 1;
    this.raycaster.setFromCamera(this.mouse, this.camera);
    const hits = this.raycaster.intersectObject(this.countryMesh, false);
    if (hits.length === 0) return null;
    return this.art.triangleEntity[hits[0].faceIndex!];
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
