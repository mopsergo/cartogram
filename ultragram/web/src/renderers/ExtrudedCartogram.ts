/**
 * Cinematic 2.5D Mode (Plan §7.3): identische XY-Positionen und
 * Dreiecksind wie Flat, Extrusion entlang Z, Seitenwände pro Region,
 * weiche Beleuchtung, begrenzte Höhe gegen visuelle Überdeckung.
 *
 * Höhe: log1p(Gesamtenergie)/log1p(globaler Referenz) × max_fraction
 * × Weltbreite (Plan §8; im Manifest dokumentiert).
 */
import * as THREE from "three";
import { Artifacts } from "../data/types";
import { FrameUpdate, buildRingSegments, expandToTriangles, lerpPositions }
  from "./shared";

const SIDE_DARKEN = 0.62;   // Seitenwände dunkler als die Deckfläche
const SIDE_EPSILON = 2.5e-4; // Ring-Schrumpfung gegen koplanare Wände

export class ExtrudedCartogram {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private group = new THREE.Group();

  private art: Artifacts;
  private topMesh!: THREE.Mesh;
  private sidesMesh!: THREE.Mesh;
  private boundaryLines!: THREE.LineSegments;
  private segments: ReturnType<typeof buildRingSegments>;
  private vertexXY: Float32Array;
  private expandedXY: Float32Array;
  private sidePositions: Float32Array;   // Segmente × 6 × 3
  private linePositions: Float32Array;   // Segmente × 2 × 3
  private ringCentroids: Float32Array;   // Ringe × 2
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();
  private controls: OrbitLike;
  private worldWidth: number;
  private centerX: number;
  private centerY: number;
  private aspect = 1;

  constructor(art: Artifacts, domElement: HTMLElement) {
    this.art = art;
    const nV = art.manifest.dimensions.num_vertices;
    const nT = art.manifest.dimensions.num_triangles;
    this.vertexXY = new Float32Array(nV * 2);
    this.expandedXY = new Float32Array(nT * 3 * 2);
    this.segments = buildRingSegments(art);
    this.sidePositions = new Float32Array(this.segments.length * 6 * 3);
    this.linePositions = new Float32Array(this.segments.length * 2 * 3);

    // Ring-Zentroide für die Epsilon-Schrumpfung
    this.ringCentroids = new Float32Array(art.rings.length * 2);
    art.rings.forEach((ring, r) => {
      let sx = 0, sy = 0;
      const ids = ring.vertexIds;
      for (let i = 0; i < ids.length; i++) {
        sx += art.positionsOriginal[ids[i] * 2];
        sy += art.positionsOriginal[ids[i] * 2 + 1];
      }
      this.ringCentroids[r * 2] = sx / ids.length;
      this.ringCentroids[r * 2 + 1] = sy / ids.length;
    });

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (let i = 0; i < nV; i++) {
      const x = art.positionsOriginal[i * 2];
      const y = art.positionsOriginal[i * 2 + 1];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    this.worldWidth = maxX - minX;
    this.centerX = (minX + maxX) / 2;
    this.centerY = (minY + maxY) / 2;

    this.scene.background = new THREE.Color(0x0d1117);
    this.scene.add(this.group);

    // Beleuchtung
    const dir = new THREE.DirectionalLight(0xffffff, 1.35);
    dir.position.set(0.35, -0.75, 1.0);
    this.scene.add(dir);
    const fill = new THREE.DirectionalLight(0x8fb7d6, 0.35);
    fill.position.set(-0.6, 0.4, 0.5);
    this.scene.add(fill);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.52));

    this.camera = new THREE.PerspectiveCamera(
      42, 1, 1e4, 1.2e8);
    this.camera.position.set(
      this.centerX, this.centerY - this.worldWidth * 0.72,
      this.worldWidth * 0.66);
    this.camera.lookAt(this.centerX, this.centerY, 0);

    this.controls = makeOrbitControls(
      this.camera, domElement, this.centerX, this.centerY, 78);
    this.controls.setTarget(this.centerX, this.centerY, 0);

    this.buildMeshes();
  }

  private buildMeshes(): void {
    const art = this.art;
    const nT = art.manifest.dimensions.num_triangles;

    // Deckfläche (z = Höhe je Entität). MeshBasicMaterial: die
    // Farbskala bleibt ungefiltert sichtbar (wie in der Flachansicht);
    // die Plastizität liefern die schattierten Seitenwände.
    const topGeom = new THREE.BufferGeometry();
    topGeom.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(nT * 3 * 3), 3));
    topGeom.setAttribute("color",
      new THREE.BufferAttribute(new Float32Array(nT * 3 * 3), 3));
    this.topMesh = new THREE.Mesh(topGeom, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide,
    }));
    this.group.add(this.topMesh);

    // Seitenwände: 2 Dreiecke je Ringsegment, Non-Indexed
    const sideGeom = new THREE.BufferGeometry();
    sideGeom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(this.sidePositions.length), 3));
    sideGeom.setAttribute("color", new THREE.BufferAttribute(
      new Float32Array(this.segments.length * 6 * 3), 3));
    this.sidesMesh = new THREE.Mesh(sideGeom,
      new THREE.MeshLambertMaterial({
        vertexColors: true, side: THREE.DoubleSide }));
    this.group.add(this.sidesMesh);

    // Grenzlinien auf der Deckfläche
    const lineGeom = new THREE.BufferGeometry();
    lineGeom.setAttribute("position", new THREE.BufferAttribute(
      new Float32Array(this.linePositions.length), 3));
    this.boundaryLines = new THREE.LineSegments(lineGeom,
      new THREE.LineBasicMaterial({
        color: 0x0b0f16, transparent: true, opacity: 0.5 }));
    this.group.add(this.boundaryLines);
  }

  updateFrame(update: FrameUpdate): void {
    const art = this.art;
    const nT = art.manifest.dimensions.num_triangles;
    lerpPositions(art, update.frameA, update.frameB, update.t, this.vertexXY);
    expandToTriangles(this.vertexXY, art.expandMap, this.expandedXY);

    const heights = update.heights ??
      new Float32Array(art.manifest.dimensions.num_entities);

    // Deckfläche: XY + Z je Entitätshöhe
    const posAttr = this.topMesh.geometry.attributes
      .position as THREE.BufferAttribute;
    const pos = posAttr.array as Float32Array;
    const colorAttr = this.topMesh.geometry.attributes
      .color as THREE.BufferAttribute;
    const colors = colorAttr.array as Float32Array;
    for (let t = 0; t < nT; t++) {
      const e = art.triangleEntity[t];
      const h = heights[e];
      const r = update.entityColors[e * 3];
      const g = update.entityColors[e * 3 + 1];
      const b = update.entityColors[e * 3 + 2];
      for (let k = 0; k < 3; k++) {
        const s = (t * 3 + k);
        pos[s * 3] = this.expandedXY[s * 2];
        pos[s * 3 + 1] = this.expandedXY[s * 2 + 1];
        pos[s * 3 + 2] = h;
        colors[s * 3] = r;
        colors[s * 3 + 1] = g;
        colors[s * 3 + 2] = b;
      }
    }
    posAttr.needsUpdate = true;
    colorAttr.needsUpdate = true;

    // Seitenwände + Grenzlinien: Ringe mit Epsilon-Schrumpfung Richtung
    // Ringzentroid (verhindert koplanare Wände gleicher Nachbarn)
    const sidePos = (this.sidesMesh.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    const sideCol = (this.sidesMesh.geometry.attributes
      .color as THREE.BufferAttribute).array as Float32Array;
    const linePos = (this.boundaryLines.geometry.attributes
      .position as THREE.BufferAttribute).array as Float32Array;
    const eps = this.worldWidth * SIDE_EPSILON;

    let sp = 0, lp = 0;
    this.art.rings.forEach((ring, r) => {
      const cx = this.ringCentroids[r * 2];
      const cy = this.ringCentroids[r * 2 + 1];
      const e = ring.entity;
      const h = heights[e];
      const ids = ring.vertexIds;
      for (let i = 0; i < ids.length; i++) {
        const v0 = ids[i], v1 = ids[(i + 1) % ids.length];
        let x0 = this.vertexXY[v0 * 2], y0 = this.vertexXY[v0 * 2 + 1];
        let x1 = this.vertexXY[v1 * 2], y1 = this.vertexXY[v1 * 2 + 1];
        // Schrumpfung
        let dx = cx - x0, dy = cy - y0;
        let len = Math.hypot(dx, dy) || 1;
        x0 += (dx / len) * eps; y0 += (dy / len) * eps;
        dx = cx - x1; dy = cy - y1;
        len = Math.hypot(dx, dy) || 1;
        x1 += (dx / len) * eps; y1 += (dy / len) * eps;

        // Seitenwand: (b0, b1, t1) + (b0, t1, t0)
        const rC = update.entityColors[e * 3] * SIDE_DARKEN;
        const gC = update.entityColors[e * 3 + 1] * SIDE_DARKEN;
        const bC = update.entityColors[e * 3 + 2] * SIDE_DARKEN;
        sidePos[sp] = x0; sidePos[sp + 1] = y0; sidePos[sp + 2] = 0;
        sidePos[sp + 3] = x1; sidePos[sp + 4] = y1; sidePos[sp + 5] = 0;
        sidePos[sp + 6] = x1; sidePos[sp + 7] = y1; sidePos[sp + 8] = h;
        sidePos[sp + 9] = x0; sidePos[sp + 10] = y0; sidePos[sp + 11] = 0;
        sidePos[sp + 12] = x1; sidePos[sp + 13] = y1; sidePos[sp + 14] = h;
        sidePos[sp + 15] = x0; sidePos[sp + 16] = y0; sidePos[sp + 17] = h;
        for (let k = 0; k < 6; k++) {
          sideCol[sp + k * 3] = rC;
          sideCol[sp + k * 3 + 1] = gC;
          sideCol[sp + k * 3 + 2] = bC;
        }
        sp += 18;

        linePos[lp] = x0; linePos[lp + 1] = y0; linePos[lp + 2] = h;
        linePos[lp + 3] = x1; linePos[lp + 4] = y1; linePos[lp + 5] = h;
        lp += 6;
      }
    });
    (this.sidesMesh.geometry.attributes.position as THREE.BufferAttribute)
      .needsUpdate = true;
    (this.sidesMesh.geometry.attributes.color as THREE.BufferAttribute)
      .needsUpdate = true;
    (this.boundaryLines.geometry.attributes.position as THREE.BufferAttribute)
      .needsUpdate = true;
    this.topMesh.geometry.computeBoundingSphere();
    this.sidesMesh.geometry.computeBoundingSphere();
  }

  applyCamera(): void {
    this.controls.update();
  }

  resize(width: number, height: number): void {
    this.aspect = width / Math.max(height, 1);
    this.camera.aspect = this.aspect;
    this.camera.updateProjectionMatrix();
  }

  resetCamera(): void {
    this.camera.position.set(
      this.centerX, this.centerY - this.worldWidth * 0.72,
      this.worldWidth * 0.66);
    this.controls.setTarget(this.centerX, this.centerY, 0);
    this.controls.update();
  }

  pick(clientX: number, clientY: number, width: number,
       height: number): number | null {
    this.mouse.x = (clientX / width) * 2 - 1;
    this.mouse.y = -(clientY / height) * 2 + 1;
    this.raycaster.setFromCamera(this.mouse, this.camera);
    const hits = this.raycaster.intersectObject(this.topMesh, false);
    if (hits.length === 0) return null;
    return this.art.triangleEntity[hits[0].faceIndex!];
  }
}

/** Minimale Orbit-Steuerung (Drag = Rotation, Rad = Zoom, Shift-Drag = Pan). */
export interface OrbitLike {
  update(): void;
  setTarget(x: number, y: number, z: number): void;
  dispose(): void;
}

function makeOrbitControls(camera: THREE.PerspectiveCamera,
                           dom: HTMLElement, cx: number, cy: number,
                           maxPolarDeg: number): OrbitLike {
  // Lokale Implementierung (kein Beispiel-Import nötig)
  const spherical = { theta: -Math.PI / 2, phi: 0.92, radius: 0 };
  const target = new THREE.Vector3(cx, cy, 0);
  const maxPolar = maxPolarDeg * Math.PI / 180;

  function syncFromCamera() {
    const off = camera.position.clone().sub(target);
    spherical.radius = off.length();
    spherical.theta = Math.atan2(off.x, off.y);
    spherical.phi = Math.acos(Math.min(Math.max(
      off.z / (spherical.radius || 1), -1), 1));
  }
  syncFromCamera();

  function applyToCamera() {
    const phi = Math.min(Math.max(spherical.phi, 0.12), maxPolar);
    const r = spherical.radius;
    camera.position.set(
      target.x + r * Math.sin(phi) * Math.sin(spherical.theta),
      target.y + r * Math.sin(phi) * Math.cos(spherical.theta),
      target.z + r * Math.cos(phi));
    camera.lookAt(target);
  }

  let rotating = false, panning = false;
  let lastX = 0, lastY = 0;

  dom.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    rotating = !e.shiftKey;
    panning = e.shiftKey;
    lastX = e.clientX;
    lastY = e.clientY;
    dom.setPointerCapture(e.pointerId);
  });
  dom.addEventListener("pointermove", (e) => {
    if (!rotating && !panning) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    if (rotating) {
      spherical.theta -= dx * 0.005;
      spherical.phi -= dy * 0.005;
    } else if (panning) {
      const scale = spherical.radius * 0.0012;
      const right = new THREE.Vector3().crossVectors(
        camera.up, camera.getWorldDirection(new THREE.Vector3())).normalize();
      const up = new THREE.Vector3().crossVectors(
        camera.getWorldDirection(new THREE.Vector3()), right).normalize();
      target.addScaledVector(right, -dx * scale);
      target.addScaledVector(up, dy * scale);
    }
  });
  dom.addEventListener("pointerup", () => { rotating = false; panning = false; });
  dom.addEventListener("wheel", (e) => {
    e.preventDefault();
    spherical.radius *= Math.exp(e.deltaY * 0.0011);
    spherical.radius = Math.min(Math.max(spherical.radius, 5e5), 8e7);
  }, { passive: false });

  return {
    update: applyToCamera,
    setTarget(x: number, y: number, z: number) {
      target.set(x, y, z);
      syncFromCamera();
    },
    dispose() { /* Listener leben mit dem DOM-Element */ },
  };
}
