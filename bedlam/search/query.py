"""Tavily query formulation (Nano): dependency + resolved version + failure term.

The model chooses *which* dependency and *what* failure to search for. It
never writes the version -- that is filled in from the lockfile, so a query
can't drift to a version the target doesn't run. It can't search the
boilerplate's own name either: the dependency must be in the manifest, and
a failure term naming the boilerplate is rejected. Searching the boilerplate
name returns noise.

A reply short of new queries is retried with the reason. If every attempt
still falls short -- Nano repeating an earlier round's query is the usual
case -- the run goes on with the most new queries any attempt produced, as
long as there is at least one. That is logged and marked on the queries:
one live search is worth more than a stopped run.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Final

from bedlam import prompts
from bedlam.diff import DiffAnalysis
from bedlam.history import FaultRecord
from bedlam.logging import get_logger
from bedlam.models.client import ModelCallError, ModelClient
from bedlam.models.map import CallSite
from bedlam.probes.classify import Symptom
from bedlam.search.manifest import Dependency, lookup

_LOG = get_logger("bedlam.search.query")

QUERIES_PER_CYCLE: Final = 2
_BANNED_TERMS: Final = re.compile(r"boilerplate|benavlabs", re.IGNORECASE)
_TERM_WORDS: Final = (2, 8)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    dependency: str
    version: str
    failure_term: str
    # True when the round ran short: every attempt fell short of
    # QUERIES_PER_CYCLE new queries, and this one was the best left.
    short: bool = False

    @property
    def text(self) -> str:
        return f"{self.dependency} {self.version} {self.failure_term}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "text": self.text}


def _parser(manifest: tuple[Dependency, ...], previous: set[str], best: list[SearchQuery]):
    """Parse one reply. `best` keeps the most usable queries any reply held."""

    def parse(value: Any) -> tuple[SearchQuery, ...]:
        queries: list[SearchQuery] = []
        skipped: list[str] = []
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
            # A skipped query is named in the rejection: a bare "need N new
            # queries" left Nano repeating the same mistake on its retry.
            if query.text in previous:
                skipped.append(
                    f"`{dep.name}` + `{term}` was already searched in an earlier round; "
                    "change the failure term or pick another dependency"
                )
                continue
            if dep.name in seen:
                skipped.append(f"two queries target `{dep.name}`; each needs its own dependency")
                continue
            seen.add(dep.name)
            queries.append(query)
        if len(queries) > len(best):
            best[:] = queries
        if len(queries) < QUERIES_PER_CYCLE:
            reasons = "; ".join(skipped) or f"the reply held {len(queries)} queries"
            raise ValueError(
                f"need {QUERIES_PER_CYCLE} new queries on distinct dependencies, "
                f"got {len(queries)} usable: {reasons}"
            )
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
    best: list[SearchQuery] = []
    try:
        return await _ask(client, manifest, history, symptom, analysis, previous_queries, best)
    except ModelCallError as exc:
        if not best:
            raise
        _LOG.warning(
            "query formulation short",
            extra={
                "fields": {
                    "queries": [q.text for q in best],
                    "wanted": QUERIES_PER_CYCLE,
                    "error": str(exc),
                }
            },
        )
        return tuple(SearchQuery(q.dependency, q.version, q.failure_term, short=True) for q in best)


async def _ask(
    client: ModelClient,
    manifest: tuple[Dependency, ...],
    history: list[FaultRecord],
    symptom: Symptom | None,
    analysis: DiffAnalysis | None,
    previous_queries: list[str],
    best: list[SearchQuery],
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
        parse=_parser(manifest, set(previous_queries), best),
    )
