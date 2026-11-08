# Calotype — local infra (Compose)

| Variable | Default | Description |
|----------|---------|--------------|
| `LR_FF_POSTGRES_PORT` | `5432` | Host port Postgres |
| `LR_FF_POSTGRES_DB` | `calotype` | Database name |
| `LR_FF_POSTGRES_USER` | `calotype` | DB user |
| `LR_FF_POSTGRES_PASSWORD` | `calotype` | DB password (**fine in dev, rotate in prod**) |
| `LR_FF_REDIS_PORT` | `6379` | Host port Redis (job queue) |
| `LR_FF_MINIO_PORT` | `9000` | S3-compatible API port |
| `LR_FF_MINIO_CONSOLE_PORT` | `9001` | MinIO web UI |
| `LR_FF_MINIO_USER` | `minio` | Root user |
| `LR_FF_MINIO_PASSWORD` | `miniosecret_changeme` | Root password |

API/worker (later, not all included in Compose):

| Variable | Example | Description |
|----------|----------|--------------|
| `DATABASE_URL` | `postgresql+psycopg://calotype:calotype@127.0.0.1:5432/calotype` | SQLAlchemy/async URL |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Broker / result backend |
| `S3_ENDPOINT` | `http://127.0.0.1:9000` | S3 API (RustFS; any S3 endpoint works) |
| `S3_ACCESS_KEY` | `minio` | Access key |
| `S3_SECRET_KEY` | `miniosecret_changeme` | Secret key |
| `S3_BUCKET` | `calotype-photos` | Artifact bucket |

Start:

```bash
docker compose up -d
```
