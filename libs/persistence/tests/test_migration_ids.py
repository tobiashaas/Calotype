"""Every Alembic revision id fits `alembic_version.version_num` (varchar(32)) and the chain is linear.

Found 2026-11-24: migration 017's id had 34 characters; `alembic upgrade head` failed on Postgres
with "value too long for type character varying(32)" — no unit test ever runs the migrations.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[3] / "infra" / "migrations" / "versions"
ID = re.compile(r'^(down_revision|revision)\s*(?::[^=]*)?=\s*"([^"]*)"', re.M)


def _revisions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for f in sorted(VERSIONS.glob("*.py")):
        found = dict(ID.findall(f.read_text(encoding="utf-8")))
        assert "revision" in found, f"{f.name}: no revision id"
        out[found["revision"]] = found.get("down_revision")
    return out


def test_every_revision_id_fits_alembics_column():
    too_long = [r for r in _revisions() if len(r) > 32]
    assert not too_long, f"revision ids longer than 32 characters: {too_long}"


def test_the_chain_is_linear_with_one_head():
    revisions = _revisions()
    children: dict[str | None, list[str]] = {}
    for rev, down in revisions.items():
        children.setdefault(down, []).append(rev)
    assert all(len(c) == 1 for c in children.values()), f"branches in the chain: {children}"
    heads = set(revisions) - {d for d in revisions.values() if d}
    assert len(heads) == 1, f"more than one head: {heads}"
