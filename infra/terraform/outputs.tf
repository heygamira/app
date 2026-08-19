output "api_url" {
  description = "The API's Cloud Run URL. Point the Family Dashboard's and Parent App's VITE_GAMIRA_API_URL at this + /api/v1 (see docs/ANDROID_AND_CLOUD.md's API address note), or at the custom domain once one is mapped."
  value       = google_cloud_run_v2_service.api.uri
}

output "cloud_sql_connection_name" {
  description = "PROJECT:REGION:INSTANCE — needed by the Cloud SQL Auth Proxy for any out-of-band access (e.g. a one-off psql session), and matches what cloud_run.tf already wires into every service's volumes block."
  value       = google_sql_database_instance.gamira.connection_name
}

output "artifact_registry_repo" {
  description = "Push images here: REGION-docker.pkg.dev/PROJECT/gamira/backend:TAG."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.gamira.repository_id}"
}

output "uploads_bucket" {
  value = google_storage_bucket.uploads.name
}

output "runtime_service_account_email" {
  value = google_service_account.runtime.email
}

output "deployer_service_account_email" {
  description = "Grant this identity to whatever runs the deploy pipeline (a GitHub Actions Workload Identity Federation binding, not a downloaded key file)."
  value       = google_service_account.deployer.email
}

output "migration_job_name" {
  description = "gcloud run jobs execute this --wait, as the deploy pipeline's explicit migration step, before deploying a new API/worker revision."
  value       = google_cloud_run_v2_job.migrate.name
}
