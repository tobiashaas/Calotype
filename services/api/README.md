Thin FastAPI layer: enqueue jobs (202 Accepted), no image processing in the request path.

```bash
cd services/api
python -m venv .venv
.venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn calotype_api.main:app --reload
```
