# Database migrations (Alembic)

From the repo root or this folder:

```bash
set DATABASE_URL=postgresql+psycopg://lrframeflow:lrframeflow@127.0.0.1:5432/lrframeflow
cd infra/migrations
pip install -e ../../libs/domain -e ../../libs/persistence alembic
alembic upgrade head
```

`prepend_sys_path` in `alembic.ini` adds the monorepo root, so `lr_frameflow_persistence` is importable.
