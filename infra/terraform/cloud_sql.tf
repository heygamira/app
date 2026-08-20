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
    # This project's org policy defaults new Cloud SQL instances to the
    # ENTERPRISE_PLUS edition, which requires db-perf-optimized-N-* tier
    # names instead of the classic db-custom-N-M naming var.db_tier uses —
    # pin the edition explicitly rather than switch tier naming schemes.
    edition           = "ENTERPRISE"
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
      # GCP now requires at least one connectivity path (public IP, private
      # IP via VPC peering, or PSC) at instance-creation time — there's no
      # VPC/private-service-access setup in this stack, so this must be
      # true. This does not mean the database is open to the internet: no
      # authorized_networks are listed below, so the firewall rejects direct
      # connections from any IP. Cloud Run's actual connection goes through
      # the Cloud SQL Auth Proxy (the /cloudsql socket mount in cloud_run.tf),
      # which authenticates via IAM and mutual TLS over Google's internal
      # network, not a raw connection to this public IP.
      ipv4_enabled = true
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
