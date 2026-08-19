resource "google_artifact_registry_repository" "gamira" {
  repository_id = "gamira"
  project       = var.project_id
  location      = var.region
  format        = "DOCKER"
  description   = "Gamira backend container images (${var.environment})."

  # Keeps a bounded, useful history instead of every build forever: enough to
  # roll back a bad promotion, not so much the repo grows without limit.
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20
    }
  }

  cleanup_policies {
    id     = "delete-old-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "1209600s" # 14 days
    }
  }

  depends_on = [google_project_service.required]
}
