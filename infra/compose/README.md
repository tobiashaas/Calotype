# LR-FrameFlow — lokale Infra (Compose)

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `LR_FF_POSTGRES_PORT` | `5432` | Host-Port Postgres |
| `LR_FF_POSTGRES_DB` | `lrframeflow` | Datenbankname |
| `LR_FF_POSTGRES_USER` | `lrframeflow` | DB-User |
| `LR_FF_POSTGRES_PASSWORD` | `lrframeflow` | DB-Passwort (**in Dev ok, in Prod rotieren**) |
| `LR_FF_REDIS_PORT` | `6379` | Host-Port Redis (Job-Queue) |
| `LR_FF_MINIO_PORT` | `9000` | S3-kompatibler API-Port |
| `LR_FF_MINIO_CONSOLE_PORT` | `9001` | MinIO Web-UI |
| `LR_FF_MINIO_USER` | `minio` | Root-User |
| `LR_FF_MINIO_PASSWORD` | `miniosecret_changeme` | Root-Passwort |

API/Worker (später, nicht alle im Compose enthalten):

| Variable | Beispiel | Beschreibung |
|----------|----------|--------------|
| `DATABASE_URL` | `postgresql+psycopg://lrframeflow:lrframeflow@127.0.0.1:5432/lrframeflow` | SQLAlchemy/async URL |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Broker / Result backend |
| `S3_ENDPOINT` | `http://127.0.0.1:9000` | S3 API (RustFS; any S3 endpoint works) |
| `S3_ACCESS_KEY` | `minio` | Access Key |
| `S3_SECRET_KEY` | `miniosecret_changeme` | Secret Key |
| `S3_BUCKET` | `lr-frameflow` | Artefakt-Bucket |

Start:

```bash
docker compose up -d
```
