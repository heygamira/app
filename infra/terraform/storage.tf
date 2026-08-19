# Private object storage — docs/ANDROID_AND_CLOUD.md's deployment sequence
# step 5. Provisioned ahead of the code that will use it: ROADMAP.md Phase 5
# ("Add file metadata and authenticated upload/download flow", "Add
# prescription/report upload with malware and file-type checks") is not built
# yet, so gamira-backend/app/core/config.py's FILE_STORAGE_BACKEND stays
# "local" until that ships — this bucket exists so the backend work has
# somewhere real to point at instead of that also being a deploy-time
# scramble.

resource "google_storage_bucket" "uploads" {
  name     = "${local.name_prefix}-uploads-${var.project_id}"
  project  = var.project_id
  location = var.region

  # Private by construction, not by a since-forgotten IAM policy: uniform
  # bucket-level access plus public access prevention rules out both an
  # object-level ACL and an org-policy exception ever making a file public.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      # Old versions only — current objects are governed by the retention
      # policy the eventual upload feature defines (docs/ROADMAP.md: "Add
      # consent and data-retention controls"), not by a blanket bucket rule.
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "runtime_object_admin" {
  # Object-level, not bucket-level admin: the app manages the files it
  # writes, not the bucket's own configuration (lifecycle rules, IAM) — and
  # scoped to this one bucket, not every bucket in the project.
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
