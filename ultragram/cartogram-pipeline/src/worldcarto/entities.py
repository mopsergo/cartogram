"""Entitätenregister (Plan §5.2): entities.yaml -> Objekte."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Entity:
    index: int
    id: str
    display_name: str
    source_names: tuple[str, ...]
    geometry_members: tuple[str, ...]
    macroarea: str
    historical_aggregate: bool = False
    is_other_world: bool = False
    note: str = ""


@dataclass(frozen=True)
class EntityRegistry:
    entities: tuple[Entity, ...]
    macroarea_labels: dict[str, str]

    _by_id: dict[str, Entity] = field(init=False, repr=False, default=None)
    _by_source: dict[str, Entity] = field(init=False, repr=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "_by_id", {e.id: e for e in self.entities})
        by_source: dict[str, Entity] = {}
        for e in self.entities:
            for name in e.source_names:
                if name in by_source:
                    raise ValueError(
                        f"Quellname {name!r} ist mehreren Entitäten zugeordnet "
                        f"({by_source[name].id}, {e.id})"
                    )
                by_source[name] = e
        object.__setattr__(self, "_by_source", by_source)

    def __len__(self) -> int:
        return len(self.entities)

    def __iter__(self):
        return iter(self.entities)

    def __getitem__(self, index: int) -> Entity:
        return self.entities[index]

    def by_id(self, entity_id: str) -> Entity:
        return self._by_id[entity_id]

    def by_source(self, country_name: str) -> Entity | None:
        return self._by_source.get(country_name)

    def index_of(self, entity_id: str) -> int:
        return self._by_id[entity_id].index

    def ids(self) -> list[str]:
        return [e.id for e in self.entities]

    def other_world(self) -> Entity:
        return self._by_id["OTHER_WORLD"]

    def macroarea_label(self, code: str) -> str:
        return self.macroarea_labels.get(code, code or "Rest der Welt")


def load_registry(path: Path | None = None) -> EntityRegistry:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "configs" / "entities.yaml"
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    entities: list[Entity] = []
    for i, e in enumerate(raw["entities"]):
        entities.append(Entity(
            index=i,
            id=str(e["id"]),
            display_name=str(e["display_name"]),
            source_names=tuple(str(s) for s in e.get("source_names") or ()),
            geometry_members=tuple(str(g) for g in e.get("geometry_members") or ()),
            macroarea=str(e.get("macroarea", "")),
            historical_aggregate=bool(e.get("historical_aggregate", False)),
            is_other_world=bool(e.get("is_other_world", False)),
            note=str(e.get("note", "")),
        ))

    ids = [e.id for e in entities]
    if len(ids) != len(set(ids)):
        raise ValueError("Doppelte Entitäts-IDs im Register")
    if sum(e.is_other_world for e in entities) != 1:
        raise ValueError("Genau eine Entität muss is_other_world sein")

    return EntityRegistry(
        entities=tuple(entities),
        macroarea_labels={str(k): str(v) for k, v in (raw.get("macroarea_labels") or {}).items()},
    )
