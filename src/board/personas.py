from __future__ import annotations

from src.models import Persona


def load_personas(raw_personas: list[dict]) -> list[Persona]:
    return [Persona(name=p["name"], role=p["role"]) for p in raw_personas]
