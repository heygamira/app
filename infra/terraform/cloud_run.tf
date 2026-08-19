# Two services from one image, per docs/ARCHITECTURE.md and TODO.md: the API
# answers requests, the worker (python -m app.worker) drains the job queue —
# separate processes today even in local dev (run.py starts both), and
# app/services/realtime.py's Postgres LISTEN/NOTIFY move exists specifically
# because they don't share memory. Cloud Tasks/Scheduler replacing the
# worker's own ticking (WORKER_RUN_SCHEDULER=false) is the documented future
# step once a Cloud Tasks-triggered HTTP handler exists — nothing in the
# codebase implements that path yet, so this keeps the worker self-ticking,
# which is fully supported today and correct at this scale.

locals {
  common_env = [
    { name = "APP_ENV", value = var.environment },
    { name = "GAMIRA_DEBUG", value = "false" },
    { name = "CORS_ORIGINS", value = var.cors_origins },
    { name = "AUTH_MODE", value = "firebase" },
    { name = "FIREBASE_PROJECT_ID", value = var.firebase_project_id },
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "LOG_FORMAT", value = "json" },
    { name = "FCM_PROVIDER", value = "firebase" },
    { name = "FCM_PROJECT_ID", value = var.firebase_project_id },
    { name = "FCM_CREDENTIALS_FILE", value = "/secrets/fcm/fcm-credentials.json" },
    { name = "AI_PROVIDER", value = "gemini" },
    # Unbuilt: gamira-backend/app/core/config.py accepts "gcs" but nothing
    # implements that backend yet (docs/ROADMAP.md Phase 5). Change this once
    # it does — storage.tf's bucket is already provisioned and waiting.
    { name = "FILE_STORAGE_BACKEND", value = "local" },
  ]

  common_secret_env = [
    { name = "DATABASE_URL", secret = google_secret_manager_secret.database_url.secret_id },
    { name = "GEMINI_API_KEY", secret = google_secret_manager_secret.gemini_api_key.secret_id },
  ]
}

# --- API service ------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = "${local.name_prefix}-api"
  project  = var.project_id
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL" # the public API surface; see docs/ANDROID_AND_CLOUD.md's "API address" note on why a public URL is fine

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.api_max_instances
    }

    containers {
      image = var.backend_image

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      dynamic "env" {
        for_each = local.common_secret_env
        content {
          name = env.value.name
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      volume_mounts {
        name       = "fcm-credentials"
        mount_path = "/secrets/fcm"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      # /ready is the readiness check this endpoint exists for (503 when the
      # database is unreachable) — /health always reports 200 and is the
      # wrong probe here on purpose (see app/api/v1/health.py).
      startup_probe {
        http_get {
          path = "/ready"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 30
        failure_threshold     = 3
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.gamira.connection_name]
      }
    }

    volumes {
      name = "fcm-credentials"
      secret {
        secret = google_secret_manager_secret.fcm_credentials.secret_id
        items {
          path    = "fcm-credentials.json"
          version = "latest"
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_version.gemini_api_key,
    google_secret_manager_secret_version.fcm_credentials,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Worker service ----------------------------------------------------------
# Not request-driven and not publicly reachable — see app/worker.py's own
# docstring for the TCP-only health probe this depends on.

resource "google_cloud_run_v2_service" "worker" {
  name     = "${local.name_prefix}-worker"
  project  = var.project_id
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.runtime.email

    scaling {
      # Always at least one: the worker is what actually sends reminders,
      # advances missed doses and escalates SOS. Zero instances here means
      # none of that runs, not just "runs late."
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_min_instances
    }

    containers {
      image   = var.backend_image
      command = ["python", "-m", "app.worker"]

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      dynamic "env" {
        for_each = local.common_secret_env
        content {
          name = env.value.name
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      volume_mounts {
        name       = "fcm-credentials"
        mount_path = "/secrets/fcm"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        tcp_socket {}
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 10
      }

      liveness_probe {
        tcp_socket {}
        period_seconds     = 30
        failure_threshold  = 3
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.gamira.connection_name]
      }
    }

    volumes {
      name = "fcm-credentials"
      secret {
        secret = google_secret_manager_secret.fcm_credentials.secret_id
        items {
          path    = "fcm-credentials.json"
          version = "latest"
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_version.database_url,
    google_secret_manager_secret_version.gemini_api_key,
    google_secret_manager_secret_version.fcm_credentials,
  ]
}

# --- Migration job -----------------------------------------------------------
# docs/ANDROID_AND_CLOUD.md deployment sequence step 7: "Deploy database
# migrations as an explicit controlled step" — a Cloud Run Job the deploy
# pipeline runs and waits on *before* deploying a new API/worker revision,
# never something either service does for itself on startup (the Dockerfile
# comment on this is explicit: a rolling restart must not run two migrations
# at once).

resource "google_cloud_run_v2_job" "migrate" {
  name     = "${local.name_prefix}-migrate"
  project  = var.project_id
  location = var.region

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries      = 0 # a failed migration must stop the deploy, not silently retry

      containers {
        image   = var.backend_image
        command = ["python", "-m", "alembic", "upgrade", "head"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.value.name
            value = env.value.value
          }
        }

        dynamic "env" {
          for_each = local.common_secret_env
          content {
            name = env.value.name
            value_source {
              secret_key_ref {
                secret  = env.value.secret
                version = "latest"
              }
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.gamira.connection_name]
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_version.database_url,
  ]

  lifecycle {
    # The job definition (image tag) changes every deploy; Terraform should
    # own its existence and config, not fight the deploy pipeline over which
    # image tag is current between applies.
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}
