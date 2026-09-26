"""Mesh-Cache (Plan §4: Cache-Grundidee; Plan §9: build-cache/)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .topology import Mesh


def save_mesh(mesh: Mesh, path_base: Path) -> None:
    """Speichert Mesh als NPZ (Arrays) + JSON (Struktur)."""
    ring_flat = np.concatenate([ids for _, ids, _ in mesh.rings]) \
        if mesh.rings else np.zeros(0, dtype=np.int64)
    ring_meta = []
    offset = 0
    for ei, ids, is_hole in mesh.rings:
        ring_meta.append({"entity": int(ei), "is_hole": bool(is_hole),
                          "offset": offset, "len": int(len(ids))})
        offset += len(ids)

    meta = {
        "entity_ids": mesh.entity_ids,
        "num_entities": mesh.num_entities,
        "num_vertices": mesh.num_vertices,
        "bounds": list(mesh.bounds),
        "world_bounds": list(mesh.world_bounds),
        "rings": ring_meta,
        "entity_parts": [
            [[ext, holes] for ext, holes in parts]
            for parts in mesh.entity_parts
        ],
        "adjacency": [sorted(s) for s in mesh.adjacency],
    }
    path_base.parent.mkdir(parents=True, exist_ok=True)
    (path_base.with_suffix(".json")).write_text(json.dumps(meta))
    np.savez_compressed(
        path_base.with_suffix(".npz"),
        positions=mesh.positions, lonlat=mesh.lonlat,
        triangles=mesh.triangles, triangle_entity=mesh.triangle_entity,
        entity_ranges=mesh.entity_ranges, ring_vertices=ring_flat,
    )


def load_mesh(path_base: Path) -> Mesh:
    meta = json.loads(path_base.with_suffix(".json").read_text())
    data = np.load(path_base.with_suffix(".npz"))
    ring_flat = data["ring_vertices"]
    rings = [
        (r["entity"], ring_flat[r["offset"]:r["offset"] + r["len"]],
         r["is_hole"])
        for r in meta["rings"]
    ]
    return Mesh(
        num_entities=meta["num_entities"],
        entity_ids=list(meta["entity_ids"]),
        num_vertices=meta["num_vertices"],
        positions=data["positions"],
        lonlat=data["lonlat"],
        rings=rings,
        entity_parts=[[(ext, list(holes)) for ext, holes in parts]
                      for parts in meta["entity_parts"]],
        triangles=data["triangles"],
        triangle_entity=data["triangle_entity"],
        entity_ranges=data["entity_ranges"],
        adjacency=[set(a) for a in meta["adjacency"]],
        bounds=tuple(meta["bounds"]),
        world_bounds=tuple(meta["world_bounds"]),
    )
