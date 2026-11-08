# Database migrations (Alembic)

From the repo root or this folder:

```bash
set DATABASE_URL=postgresql+psycopg://tarsier:tarsier@127.0.0.1:5432/tarsier
cd infra/migrations
pip install -e ../../libs/domain -e ../../libs/persistence alembic
alembic upgrade head
```

`prepend_sys_path` in `alembic.ini` adds the monorepo root, so `tarsier_persistence` is importable.
