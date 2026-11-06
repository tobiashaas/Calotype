#!/usr/bin/env python3
"""Validate OpenAPI + JSON Schemas (runs in CI and locally)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> None:
    contracts = ROOT / "packages" / "contracts"
    # 1. OpenAPI spec validation (Bridge ↔ API and Plugin ↔ Bridge)
    for openapi_file in sorted((contracts / "openapi").glob("*.yaml")):
        run([sys.executable, "-m", "openapi_spec_validator", str(openapi_file)])

    # 2. JSON Schema + example pairs
    #    Each tuple: (schema path relative to contracts/, example path relative to contracts/)
    checks: list[tuple[str, str]] = [
        (
            "json-schema/job-train-request-v1.schema.json",
            "examples/job-train-request.example.json",
        ),
        (
            "json-schema/job-envelope-v1.schema.json",
            "examples/job-envelope.example.json",
        ),
        (
            "json-schema/job-edit-request-v1.schema.json",
            "examples/job-edit-request.example.json",
        ),
        (
            "json-schema/photo-upload-v1.schema.json",
            "examples/photo-upload.example.json",
        ),
    ]
    for schema, example in checks:
        schema_path = contracts / schema
        example_path = contracts / example
        if not schema_path.exists():
            print(f"WARNING: schema not found, skipping: {schema_path}", file=sys.stderr)
            continue
        if not example_path.exists():
            print(f"WARNING: example not found, skipping: {example_path}", file=sys.stderr)
            continue
        run(
            [
                sys.executable,
                "-m",
                "check_jsonschema",
                "--schemafile",
                str(schema_path),
                str(example_path),
            ]
        )

    # 3. All schema files must be valid JSON (no parse errors)
    import json

    schema_dir = contracts / "json-schema"
    for schema_file in sorted(schema_dir.glob("*.json")):
        try:
            json.loads(schema_file.read_text())
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid JSON in {schema_file}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"+ json-parse OK: {schema_file.name}")

    print("\nAll contract checks passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
