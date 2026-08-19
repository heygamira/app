# docs/ANDROID_AND_CLOUD.md deployment sequence step 3: secrets in Secret
# Manager before anything that needs them. Each secret is granted to the
# runtime identity individually (service_accounts.tf deliberately has no
# blanket Secret Manager role) so a compromised container can read only what
# it was actually wired to use.

locals {
  # asyncpg (and libpq) treat a host starting with "/" as a Unix socket
  # directory rather than a hostname — this is the documented way to reach
  # Cloud SQL from Cloud Run without a public IP, through the connector Cloud
  # Run wires into /cloudsql/<connection_name> (see cloud_run.tf's volumes
  # block).
  database_url = "postgresql+asyncpg://${google_sql_user.gamira.name}:${random_password.db_password.result}@/${google_sql_database.gamira.name}?host=/cloudsql/${google_sql_database_instance.gamira.connection_name}"
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "${local.name_prefix}-database-url"
  project   = var.project_id
  labels    = local.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "${local.name_prefix}-gemini-api-key"
  project   = var.project_id
  labels    = local.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret" "fcm_credentials" {
  secret_id = "${local.name_prefix}-fcm-credentials"
  project   = var.project_id
  labels    = local.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "fcm_credentials" {
  secret      = google_secret_manager_secret.fcm_credentials.id
  secret_data = var.fcm_credentials_json
}

# --- Grant the runtime identity read access to exactly these three --------

resource "google_secret_manager_secret_iam_member" "runtime_reads_database_url" {
  secret_id = google_secret_manager_secret.database_url.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_gemini_api_key" {
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_fcm_credentials" {
  secret_id = google_secret_manager_secret.fcm_credentials.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
