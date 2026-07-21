# OpenG2P Farmer Profile Dedup Service

Standalone FastAPI service for farmer-profile national ID deduplication.

The service:

- fetches pending `UID`, `FAN`, and `RID` values directly from the farmer profile database
- treats farmers without a profile image as pending for NIDP processing
- sends only IDs that have not been deduplicated before
- calls the NIDP/Fayda `getDataById` API
- updates `g2p_reg_id` and selected `res_partner` fields directly in the farmer profile database
- stores NIDP processing status, response status, ID status, descriptions, and updated-field summaries in the service database
- can run national-ID deduplication continuously in the background
- can run post-dedup farmer approval continuously in the background
- stores persistent run/chunk/item logs in service tables

This package is intentionally separate from the Odoo registry REST API flow.

## Configuration

Copy the example file and fill it in:

```bash
cp .env.example .env
```

Important settings:

```env
COMMON_APP_HOST=0.0.0.0
COMMON_APP_PORT=8001

FARMER_DEDUP_DB_HOSTNAME=<farmer-profile-db-host>
FARMER_DEDUP_DB_PORT=5432
FARMER_DEDUP_DB_NAME=<farmer-profile-db>
FARMER_DEDUP_DB_USERNAME=<db-user>
FARMER_DEDUP_DB_PASSWORD=<db-password>

FARMER_DEDUP_NIDP_GET_DATA_BY_ID_URL=<nidp-url>/getDataById
FARMER_DEDUP_MOCK_NIDP_ENABLED=false

FARMER_DEDUP_BACKGROUND_ENABLED=true
FARMER_DEDUP_DRY_RUN=false
FARMER_DEDUP_FETCH_LIMIT=1000
FARMER_DEDUP_CHUNK_LIMIT=10
FARMER_DEDUP_INTERVAL_SECONDS=300

FARMER_DEDUP_APPROVAL_BACKGROUND_ENABLED=true
FARMER_DEDUP_APPROVAL_DRY_RUN=false
FARMER_DEDUP_APPROVAL_INTERVAL_SECONDS=300
```

For local seeded pipeline testing only, restrict the workers to seeded records:

```env
FARMER_DEDUP_PARTNER_UNIQUE_ID_PREFIX=LOCAL-FAYDA-PIPELINE
```

Leave `FARMER_DEDUP_PARTNER_UNIQUE_ID_PREFIX` empty in production unless you intentionally want to process only a subset.

## Internal Mock NIDP

For local testing, the service can expose its own mock NIDP endpoint:

```env
FARMER_DEDUP_MOCK_NIDP_ENABLED=true
FARMER_DEDUP_NIDP_GET_DATA_BY_ID_URL=http://localhost:8001/mock/getDataById
```

The mock endpoint is:

```text
POST /mock/getDataById
```

It returns deterministic successful data for local seed UID values like:

```text
1000 0000 0001
...
1000 0000 0030
```

The mock is disabled by default. Keep `FARMER_DEDUP_MOCK_NIDP_ENABLED=false` in production.

## Persistent Logs

Set the `FARMER_DEDUP_SERVICE_DB_*` values to point to the service-owned database.
On startup, the service creates these tables when `FARMER_DEDUP_SERVICE_DB_AUTO_MIGRATE=true`:

- `farmer_dedup_run`
- `farmer_dedup_chunk`
- `farmer_dedup_item`
- `farmer_approval_run`
- `farmer_approval_item`

If `FARMER_DEDUP_SERVICE_DB_NAME` is empty, the service falls back to the main farmer profile DB connection.

## Docker

Build and run with Docker Compose:

```bash
docker compose up --build -d
```

Check logs:

```bash
docker compose logs -f farmer-profile-dedup
```

Check health:

```bash
curl http://localhost:8001/health
```

Check background worker status:

```bash
curl http://localhost:8001/national-id-dedup/status
curl http://localhost:8001/farmer-approval/status
```

Stop the service:

```bash
docker compose down
```

## Docker Build Dependency

The service depends on `openg2p-fastapi-common`.
The Dockerfile installs it from GitHub by default:

```text
git+https://github.com/OpenG2P/openg2p-fastapi-common.git#subdirectory=openg2p-fastapi-common
```

To build with another branch, tag, fork, or internal mirror:

```bash
OPENG2P_FASTAPI_COMMON_REF='git+https://github.com/<org>/openg2p-fastapi-common.git@<branch>#subdirectory=openg2p-fastapi-common' \
docker compose build
```

## Production Deployment

1. Copy this repository to the production host or build/push the image from CI.
2. Create a production `.env` from `.env.example`.
3. Set `FARMER_DEDUP_DB_*` to the farmer profile PostgreSQL database.
4. Set `FARMER_DEDUP_SERVICE_DB_*` to the service log database. This can be the same DB at first, but a separate service DB is preferred.
5. Set `FARMER_DEDUP_NIDP_GET_DATA_BY_ID_URL` to the real NIDP endpoint.
6. Confirm `FARMER_DEDUP_DRY_RUN=false` only when you are ready to write updates.
7. Confirm `FARMER_DEDUP_APPROVAL_DRY_RUN=false` only when automatic approval should write `state='approved'`.
8. Start the service:

```bash
docker compose up -d
```

9. Watch logs and status endpoints:

```bash
docker compose logs -f farmer-profile-dedup
curl http://localhost:8001/national-id-dedup/status
curl http://localhost:8001/farmer-approval/status
```

When running in Docker, do not use `localhost` for Postgres or NIDP unless that dependency is inside the same container. Use the Docker service name, host IP, Kubernetes service DNS name, or production DNS name.

If `docker compose build` fails with a missing `docker-buildx` plugin, install Docker Buildx or build with the legacy builder as a temporary local workaround:

```bash
DOCKER_BUILDKIT=0 docker build -t openg2p-farmer-profile-dedup:latest .
docker compose up -d
```

## Manual Endpoints

Run one dedup cycle:

```bash
curl -X POST http://localhost:8001/national-id-dedup/run-once \
  -H 'Content-Type: application/json' \
  -d '{"limit": 10, "dry_run": true}'
```

Run one approval cycle:

```bash
curl -X POST http://localhost:8001/farmer-approval/run-once \
  -H 'Content-Type: application/json' \
  -d '{"limit": 10, "dry_run": true}'
```

## Post-Dedup Approval

The approval worker finds draft farmers whose service DB dedup log has at least
one configured ID type with:

```text
fayda_processed = true
fayda_response_status = PROCESSED
```

It then runs approval validations, computes:

```text
farmer_id = FR-<unique_id>
```

and directly updates `res_partner.state` to `approved` when all critical checks pass.

## Local Seeded Pipeline Test

Seed records into local Odoo:

```bash
cd /home/odoo-user/odoo-src/odoo
./odoo-bin shell -c debian/odoo.conf -d odoo_dev --no-http \
  < custom_addons/openg2p-farmer-profile-dedup/scripts/seed_local_pipeline_test_records.py
```

To seed a fresh second batch after the first 30 records:

```bash
cd /home/odoo-user/odoo-src/odoo
TEST_START_INDEX=31 TEST_COUNT=30 ./odoo-bin shell -c debian/odoo.conf -d odoo_dev --no-http \
  < custom_addons/openg2p-farmer-profile-dedup/scripts/seed_local_pipeline_test_records.py
```

If Odoo computes `farmer_id` during seeding, clear it before testing approval:

```bash
cd /home/odoo-user/odoo-src/odoo
TEST_START_INDEX=31 TEST_COUNT=30 ./odoo-bin shell -c debian/odoo.conf -d odoo_dev --no-http \
  < custom_addons/openg2p-farmer-profile-dedup/scripts/clear_seed_farmer_ids.py
```

Then run the service with:

```env
FARMER_DEDUP_MOCK_NIDP_ENABLED=true
FARMER_DEDUP_NIDP_GET_DATA_BY_ID_URL=http://localhost:8001/mock/getDataById
FARMER_DEDUP_PARTNER_UNIQUE_ID_PREFIX=LOCAL-FAYDA-PIPELINE
FARMER_DEDUP_FETCH_LIMIT=30
FARMER_DEDUP_APPROVAL_FETCH_LIMIT=30
FARMER_DEDUP_INTERVAL_SECONDS=30
FARMER_DEDUP_APPROVAL_INTERVAL_SECONDS=30
```

The seeded farmers are named:

```text
Seed Farmer 001
...
Seed Farmer 030
Seed Farmer 031
...
Seed Farmer 060
```

and have `unique_id` values:

```text
LOCAL-FAYDA-PIPELINE-001
...
LOCAL-FAYDA-PIPELINE-030
```
