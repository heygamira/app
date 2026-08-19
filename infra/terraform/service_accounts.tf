# Least-privilege service accounts, per docs/ANDROID_AND_CLOUD.md's
# deployment sequence step 2. Two, not one: the identity that *runs* the
# backend needs to read secrets and reach Cloud SQL; the identity that
# *deploys* it needs to push images and update the Cloud Run revision, and
# neither of those implies the other.

resource "google_service_account" "runtime" {
  account_id   = "${local.name_prefix}-runtime"
  display_name = "Gamira ${var.environment} — Cloud Run runtime identity"
  project      = var.project_id
}

resource "google_service_account" "deployer" {
  account_id   = "${local.name_prefix}-deployer"
  display_name = "Gamira ${var.environment} — CI/CD deploy identity"
  project      = var.project_id
}

# --- Runtime identity: what the running API/worker containers may do ------

resource "google_project_iam_member" "runtime_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Bucket-scoped object access lives in storage.tf, next to the bucket it
# grants access to — not a project-level role, for the same reason Secret
# Manager access below is granted per-secret rather than project-wide: the
# runtime identity should only be able to touch the one bucket and the
# specific secrets it's actually wired to, not every bucket or secret that
# might ever exist in the project.

# --- Deploy identity: what CI/CD may do ------------------------------------

resource "google_project_iam_member" "deployer_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_cloudsql_client" {
  # Needed to run the migration job (cloud_run.tf's google_cloud_run_v2_job)
  # as part of the deploy pipeline, not to reach the database directly.
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# The deployer must be able to act as the runtime identity to deploy a
# revision running as it — without this, "deploy" and "grant yourself the
# runtime identity's permissions" would be the same action.
resource "google_service_account_iam_member" "deployer_can_act_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${google_service_account.deployer.email}"
}
