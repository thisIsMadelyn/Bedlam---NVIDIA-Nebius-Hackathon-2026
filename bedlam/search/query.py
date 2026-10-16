"""Tavily query formulation (Nano): dependency + resolved version + failure term.

The model chooses *which* dependency and *what* failure to search for. It
never writes the version -- that is filled in from the lockfile, so a query
can't drift to a version the target doesn't run. It can't search the
boilerplate's own name either: the dependency must be in the manifest, and
a failure term naming the boilerplate is rejected. Searching the boilerplate
name returns noise.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Final

from bedlam import prompts
from bedlam.diff import DiffAnalysis
from bedlam.history import FaultRecord
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.probes.classify import Symptom
from bedlam.search.manifest import Dependency, lookup

QUERIES_PER_CYCLE: Final = 2
_BANNED_TERMS: Final = re.compile(r"boilerplate|benavlabs", re.IGNORECASE)
_TERM_WORDS: Final = (2, 8)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    dependency: str
    version: str
    failure_term: str

    @property
    def text(self) -> str:
        return f"{self.dependency} {self.version} {self.failure_term}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "text": self.text}


def _parser(manifest: tuple[Dependency, ...], previous: set[str]):
    def parse(value: Any) -> tuple[SearchQuery, ...]:
        queries: list[SearchQuery] = []
        seen: set[str] = set()
        for item in value["queries"]:
            dep = lookup(manifest, str(item["dependency"]))
            if dep is None:
                raise ValueError(f"{item['dependency']!r} is not a target dependency")
            term = " ".join(str(item["failure_term"]).split()).lower()
            low, high = _TERM_WORDS
            if not low <= len(term.split()) <= high:
                raise ValueError(f"failure term must be {low}-{high} words: {term!r}")
            if _BANNED_TERMS.search(term) or _BANNED_TERMS.search(dep.name):
                raise ValueError("queries target dependencies, never the boilerplate")
            query = SearchQuery(dependency=dep.name, version=dep.version, failure_term=term)
            if dep.name in seen or query.text in previous:
                continue
            seen.add(dep.name)
            queries.append(query)
        if len(queries) < QUERIES_PER_CYCLE:
            raise ValueError(f"need {QUERIES_PER_CYCLE} new queries on distinct dependencies")
        return tuple(queries[:QUERIES_PER_CYCLE])

    return parse


async def formulate(
    client: ModelClient,
    *,
    manifest: tuple[Dependency, ...],
    history: list[FaultRecord],
    symptom: Symptom | None,
    analysis: DiffAnalysis | None,
    previous_queries: list[str],
) -> tuple[SearchQuery, ...]:
    return await client.json(
        CallSite.TAVILY_QUERY_FORMULATION,
        system=prompts.load("query_formulation"),
        user=prompts.context(
            {
                "query_count": QUERIES_PER_CYCLE,
                "dependencies": [dep.name for dep in manifest],
                "faults_so_far": [record.to_dict() for record in history],
                "last_symptom": symptom.to_dict() if symptom else None,
                "last_patch": analysis.to_dict() if analysis else None,
                "previous_queries": previous_queries,
            }
        ),
        parse=_parser(manifest, set(previous_queries)),
    )
