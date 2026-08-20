# Gamira staging infrastructure

Terraform for the stack described in [`docs/ANDROID_AND_CLOUD.md`](../../docs/ANDROID_AND_CLOUD.md):
Cloud Run (API + worker), Cloud SQL PostgreSQL, Secret Manager, Artifact
Registry, private Cloud Storage, and the service accounts each of those
needs.

**This has not been applied.** No `terraform` CLI is installed on the machine
that wrote it, and no GCP project exists yet to point it at. Every resource
here was hand-written against the `google` provider's documented schema and
cross-checked against the actual backend code (`app/core/config.py`,
`app/main.py`, `app/worker.py`, `Dockerfile`) rather than run through
`terraform validate` — read it before applying, and expect to fix a typo or
two on the first `terraform plan`.

## What this covers, against the deployment sequence in ANDROID_AND_CLOUD.md

| Step | Covered by |
|---|---|
| 1. Region / data residency | `variables.tf`'s `region` (default `asia-south1`) — change and document the choice before first apply |
| 2. Least-privilege service accounts | `service_accounts.tf` |
| 3. Secrets in Secret Manager | `secret_manager.tf` |
| 4. Cloud SQL with backups + PITR | `cloud_sql.tf` |
| 5. Private object storage | `storage.tf` |
| 6. Build into Artifact Registry | `artifact_registry.tf` (the actual `docker build`/`push` is a CI step, not Terraform) |
| 7. Migrations as an explicit step | `cloud_run.tf`'s `google_cloud_run_v2_job.migrate` |
| 8. Cloud Run with health checks + bounded scaling | `cloud_run.tf` |
| 9. Tasks/Scheduler | **Deliberately not here** — see below |
| 10. Custom staging domain | `domain.tf`, optional, off by default |
| 11. Smoke/authorization/failure tests | Not infrastructure — run after apply, per the main plan's verification section |
| 12. Promote an immutable build | Process, not a resource — never point `backend_image` at `:latest` |

## What's deliberately not here

- **Cloud Tasks / Cloud Scheduler for background work.** The documented
  target architecture replaces the worker's own ticking with Cloud Scheduler
  once an HTTP handler exists for it (`WORKER_RUN_SCHEDULER=false` — see
  `app/jobs/scheduler.py`'s docstring). Nothing in the codebase implements
  that HTTP handler yet. Building the Terraform for a Cloud Tasks queue
  pointed at an endpoint that doesn't exist would be worse than not having
  it, so the worker service here runs with its own in-process scheduler
  (`WORKER_RUN_SCHEDULER` left at its default `true`), always on
  (`worker_min_instances`), which is fully supported today and correct at
  staging scale.
- **The `FILE_STORAGE_BACKEND=gcs` wiring.** The bucket exists
  (`storage.tf`), but `app/core/config.py` accepts `"gcs"` as a value with no
  actual GCS-backed implementation behind it yet (`docs/ROADMAP.md` Phase 5
  is still unbuilt). Every service here still sets `FILE_STORAGE_BACKEND=local`.
  Flip it once that code exists.
- **Production.** `environment` validates to `"staging"` or `"production"`,
  but this is meant to be applied once, into a staging project, first.
  Promoting to production should be a second `terraform apply` against a
  **separate GCP project** (a new `project_id`, ideally a separate state
  file/backend too) after staging passes its acceptance criteria — never a
  variable flip inside one project. See `docs/ANDROID_AND_CLOUD.md`: "Do not
  rely on resource-name prefixes inside one project as the only isolation
  boundary."

## A worker.py change this depends on

`app/worker.py` didn't listen on any port before this — it's a bare
`asyncio` polling loop. Cloud Run Services require every container to accept
a connection on `$PORT` to be considered healthy, so deploying the worker as
a plain Cloud Run Service would have failed its own liveness check
immediately. It now binds a TCP-only listener on `$PORT` when one is set
(harmless locally, where nothing sets `$PORT`) — see the commit that added
it for the reasoning and the manual verification that was done.

## Ordering, once you're actually ready to apply

1. Create the GCP project and enable billing (console or `gcloud projects
   create` — outside Terraform, since Terraform needs a project to point
   at).
2. Authenticate: `gcloud auth application-default login`.
3. Create a Firebase project for staging (or link this GCP project to one) —
   `firebase_project_id` needs to be real before `terraform apply`, since
   `AUTH_MODE=firebase` refuses to start without it
   (`app/core/config.py`'s `model_post_init`).
4. `cp terraform.tfvars.example terraform.tfvars` and fill it in. If you
   don't have real `gemini_api_key`/`fcm_credentials_json` values yet, leave
   the example's placeholder strings in place rather than empty strings —
   Secret Manager rejects an empty payload, and Cloud Run's containers
   reference these secrets' "latest" version just to start. Add the real
   secret version later with `gcloud secrets versions add` without
   re-running `apply`.
5. `terraform init`, `terraform plan`, read the plan, `terraform apply`.
   This creates everything **except** a real backend image — `backend_image`
   defaults to Google's own hello-world image, so the API/worker services
   exist but don't run Gamira yet.
6. Build and push the real image: `docker build -t
   REGION-docker.pkg.dev/PROJECT/gamira/backend:v1 gamira-backend/ && docker
   push ...` (or let CI do this — that's what `deployer_service_account_email`
   is for).
7. `terraform apply -var="backend_image=REGION-docker.pkg.dev/PROJECT/gamira/backend:v1"`
   to point the services at it. Before this deploys the API/worker
   revisions, run the migration job and wait for it:
   `gcloud run jobs execute <migration_job_name output> --wait`.
8. Hit `outputs.api_url`'s `/health` and `/ready`. Run the medication
   round-trip smoke test from the main plan's verification section.
9. Only then: `custom_domain` in `domain.tf`, once the domain is verified in
   Search Console.

## Connection pool vs. instance count

`api_max_instances` (default 3) × `database_pool_size + database_max_overflow`
(10 + 20 = 30, `app/core/config.py`) = up to 90 simultaneous connections from
the API alone, plus whatever the worker and migration job hold briefly. The
default `db_tier` (`db-custom-1-3840`) needs to comfortably clear that — check
the actual `max_connections` Cloud SQL derives for whatever tier you end up
choosing (it scales with instance memory, not a fixed number) before raising
`api_max_instances` past this default.
