# calotype-api

Thin FastAPI layer: stores photo previews and enqueues train / edit / cull jobs (202 Accepted) —
no image processing in the request path. Endpoints: [`CLAUDE.md`](../../CLAUDE.md#api-endpoints),
contract: [`packages/contracts/openapi/bridge-api.yaml`](../../packages/contracts/openapi/bridge-api.yaml).

```bash
cd services/api
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn calotype_api.main:app --host 127.0.0.1 --port 8080 --reload
pytest tests
```
