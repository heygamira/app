# The authoritative database. app/core/config.py refuses SQLite outside
# local/test, so this is not optional infrastructure — the API will not start
# without a real Postgres DATABASE_URL once APP_ENV is staging or production.

resource "random_id" "db_suffix" {
  # Cloud SQL instance names cannot be reused for a week after deletion; a
  # random suffix means a destroy-and-recreate during early staging setup
  # doesn't collide with the name it just gave up.
  byte_length = 2
}

resource "google_sql_database_instance" "gamira" {
  name             = "${local.name_prefix}-${random_id.db_suffix.hex}"
  project          = var.project_id
  region           = var.region
  # Matches what's running locally (TODO.md). Confirm this is still a valid
  # value at apply time — `gcloud sql tiers list` / the Cloud SQL console show
  # currently supported versions, and the exact enum string does change as
  # Google adds new major versions.
  database_version = "POSTGRES_17"

  # A production promotion should set deletion_protection = true here, or
  # remove this resource from a plan that could touch it by accident.
  deletion_protection = var.environment == "production"

  settings {
    tier              = var.db_tier
    availability_type = var.db_availability_type
    disk_autoresize   = true
    disk_type         = "PD_SSD"

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      # Kept well past the "restore drill" the staging acceptance criteria
      # call for, so a delayed drill doesn't run out of backups to restore.
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      # No public IP: reachable only through the Cloud SQL Auth Proxy
      # (Cloud Run's built-in connector) or a VPC connector, never the
      # open internet.
      ipv4_enabled = false
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "gamira" {
  name     = "gamira"
  project  = var.project_id
  instance = google_sql_database_instance.gamira.name
}

resource "random_password" "db_password" {
  length  = 32
  special = false # kept out of the connection-string URL's own special characters
}

resource "google_sql_user" "gamira" {
  name     = "gamira"
  project  = var.project_id
  instance = google_sql_database_instance.gamira.name
  password = random_password.db_password.result
}
