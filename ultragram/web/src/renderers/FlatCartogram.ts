/**
 * Flat Mode (Plan §7.2): orthografische Draufsicht auf das Cartogramm,
 * Ländergrenzen, Farbe nach ausgewählter Kennzahl, keine Extrusion.
 * Optionale Ghost-Ebene mit der unverzerrten Geografie.
 */
import * as THREE from "three";
import { Artifacts } from "../data/types";
import { FrameUpdate, PickResult, blendWithOriginal, buildRingSegments,
  expandToTriangles } from "./shared";

export class FlatCartogram {
  readonly scene = new THREE.Scene();
  readonly camera: THREE.OrthographicCamera;
  private group = new THREE.Group();

  private art: Artifacts;
  private topMesh!: THREE.Mesh;
  private boundaryLines!: THREE.LineSegments;
  private ghostLines!: THREE.LineSegments;
  private ghostWanted = true;
  private segments: ReturnType<typeof buildRingSegments>;
  private vertexXY: Float32Array;
  private expandedXY: Float32Array;
  private linePositions: Float32Array;
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();
  private zoom = 1;
  private panX = 0;
  private panY = 0;
  private centerX: number;
  private centerY: number;
  private worldWidth: number;
  private worldHeight: number;
  private aspect = 1;

  constructor(art: Artifacts) {
    this.art = art;
    const nV = art.manifest.dimensions.num_vertices;
    const nT = art.manifest.dimensions.num_triangles;
    this.vertexXY = new Float32Array(nV * 2);
    this.expandedXY = new Float32Array(nT * 3 * 2);
    this.segments = buildRingSegments(art);
    this.linePositions = new Float32Array(this.segments.length * 4);

    // Weltmaße aus der unverzerrten Basis
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (let i = 0; i < nV; i++) {
      const x = art.positionsOriginal[i * 2];
      const y = art.positionsOriginal[i * 2 + 1];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    const pad = 0.03;
    this.worldWidth = (maxX - minX) * (1 + pad);
    this.worldHeight = (maxY - minY) * (1 + pad);
    this.centerX = (minX + maxX) / 2;
    this.centerY = (minY + maxY) / 2;

    this.camera = new THREE.OrthographicCamera(
      -1, 1, 1, -1, 0.1, 4e7);
    this.camera.position.set(this.centerX, this.centerY, 2e7);
    this.camera.lookAt(this.centerX, this.centerY, 0);
    this.scene.background = new THREE.Color(0x0d1117);
    this.scene.add(this.group);

    this.buildMeshes();
  }

  private buildMeshes(): void {
    const art = this.art;
    const nT = art.manifest.dimensions.num_triangles;

    // Top-Fläche: Non-Indexed (kantenscharfe Entitätsfarben)
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(this.expandedXY.length), 2));
    geom.setAttribute("color",
      new THREE.BufferAttribute(new Float32Array(nT * 3 * 3), 3));
    this.topMesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide,
    }));
    this.group.add(this.topMesh);

    // Grenzlinien
    const lineGeom = new THREE.BufferGeometry();
    lineGeom.setAttribute("position",
      new THREE.BufferAttribute(new Float32Array(this.linePositions.length), 2));
    this.boundaryLines = new THREE.LineSegments(lineGeom,
      new THREE.LineBasicMaterial({
        color: 0x0b0f16, transparent: true, opacity: 0.6 }));
    this.group.add(this.boundaryLines);

    // Ghost: unverzerrte Referenz
    const ghostPos = new Float32Array(this.segments.length * 4);
    let w = 0;
    for (const seg of this.segments) {
      ghostPos[w++] = art.positionsOriginal[seg.v0 * 2];
      ghostPos[w++] = art.positionsOriginal[seg.v0 * 2 + 1];
      ghostPos[w++] = art.positionsOriginal[seg.v1 * 2];
      ghostPos[w++] = art.positionsOriginal[seg.v1 * 2 + 1];
    }
    const ghostGeom = new THREE.BufferGeometry();
    ghostGeom.setAttribute("position", new THREE.BufferAttribute(ghostPos, 2));
    this.ghostLines = new THREE.LineSegments(ghostGeom,
      new THREE.LineBasicMaterial({
        color: 0x39445a, transparent: true, opacity: 0.55 }));
    this.group.add(this.ghostLines);
  }

  setGhostVisible(visible: boolean): void {
    this.ghostWanted = visible;
    this.ghostLines.visible = visible;
  }

  updateFrame(update: FrameUpdate): void {
    const art = this.art;
    // Kanonische Positionen von der App übernehmen und mit der
    // Original-Geografie überblenden (Renderer-lokale Kopie)
    this.vertexXY.set(update.vertexXY);
    const geoBlend = update.geoBlend ?? 0;
    blendWithOriginal(art, this.vertexXY, geoBlend);
    // Ghost = Original-Geografie: in der Original-Ansicht identisch -> aus
    this.ghostLines.visible = this.ghostWanted && geoBlend < 0.999;
    expandToTriangles(this.vertexXY, art.expandMap, this.expandedXY);

    const posAttr = this.topMesh.geometry.attributes
      .position as THREE.BufferAttribute;
    (posAttr.array as Float32Array).set(this.expandedXY);
    posAttr.needsUpdate = true;

    // Farben je expandiertem Vertex (kantenscharf je Dreieck)
    const colorAttr = this.topMesh.geometry.attributes
      .color as THREE.BufferAttribute;
    const colors = colorAttr.array as Float32Array;
    const nT = art.manifest.dimensions.num_triangles;
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

    // Grenzlinien aus interpolierten Positionen
    const lp = this.boundaryLines.geometry.attributes
      .position as THREE.BufferAttribute;
    let w = 0;
    for (const seg of this.segments) {
      this.linePositions[w++] = this.vertexXY[seg.v0 * 2];
      this.linePositions[w++] = this.vertexXY[seg.v0 * 2 + 1];
      this.linePositions[w++] = this.vertexXY[seg.v1 * 2];
      this.linePositions[w++] = this.vertexXY[seg.v1 * 2 + 1];
    }
    (lp.array as Float32Array).set(this.linePositions);
    lp.needsUpdate = true;
  }

  /** Kamera an Zoom/Pan/Aspekt anpassen (vor dem Rendern aufrufen). */
  applyCamera(): void {
    let w = this.worldWidth / this.zoom;
    let h = w / Math.max(this.aspect, 0.1);
    if (h < this.worldHeight / this.zoom) {
      h = this.worldHeight / this.zoom;
      w = h * this.aspect;
    }
    this.camera.left = -w / 2;
    this.camera.right = w / 2;
    this.camera.top = h / 2;
    this.camera.bottom = -h / 2;
    this.camera.position.set(this.centerX + this.panX,
                             this.centerY + this.panY, 2e7);
    this.camera.updateProjectionMatrix();
  }

  resize(width: number, height: number): void {
    this.aspect = width / Math.max(height, 1);
  }

  resetCamera(): void {
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
  }

  pick(clientX: number, clientY: number, width: number,
       height: number): PickResult | null {
    this.mouse.x = (clientX / width) * 2 - 1;
    this.mouse.y = -(clientY / height) * 2 + 1;
    this.raycaster.setFromCamera(this.mouse, this.camera);
    const hits = this.raycaster.intersectObject(this.topMesh, false);
    if (hits.length === 0) return null;
    const t = hits[0].faceIndex!;
    return { entity: this.art.triangleEntity[t], triangle: t };
  }

  attachControls(container: HTMLElement): void {
    let dragging = false;
    let lastX = 0, lastY = 0;

    container.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    });
    container.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const worldPerPx =
        (this.camera.right - this.camera.left) / container.clientWidth;
      this.panX -= (e.clientX - lastX) * worldPerPx;
      this.panY += (e.clientY - lastY) * worldPerPx;
      lastX = e.clientX;
      lastY = e.clientY;
    });
    container.addEventListener("pointerup", () => { dragging = false; });
    container.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = Math.exp(e.deltaY * 0.0012);
      this.zoom = Math.min(Math.max(this.zoom / factor, 0.6), 60);
    }, { passive: false });
  }
}
