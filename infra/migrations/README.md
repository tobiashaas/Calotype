# Database migrations (Alembic)

From the repo root or this folder:

```bash
set DATABASE_URL=postgresql+psycopg://calotype:calotype@127.0.0.1:5432/calotype
cd infra/migrations
pip install -e ../../libs/domain -e ../../libs/persistence alembic
alembic upgrade head
```

`prepend_sys_path` in `alembic.ini` adds the monorepo root, so `calotype_persistence` is importable.
