# API and data contracts

This directory is the **canonical version** for:

- REST interface between **Bridge** and **FastAPI**: `openapi/bridge-api.yaml`
- JSON schemas for payloads, envelopes and events: `json-schema/` (especially **`job-envelope-v1`** for Redis)

## CI contract checks (recommended)

```bash
pip install openapi-spec-validator check-jsonschema
openapi-spec-validator openapi/bridge-api.yaml
check-jsonschema --schemafile json-schema/job-train-request-v1.schema.json examples/job-train-request.example.json
check-jsonschema --schemafile json-schema/job-envelope-v1.schema.json examples/job-envelope.example.json
```

Automated: root script `python scripts/validate_contracts.py` or workflow `.github/workflows/ci.yml`.

Type generation for the Bridge or a Python client is optional (`datamodel-codegen`, `openapi-generator-cli`).
