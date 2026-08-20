provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  name_prefix = "gamira-${var.environment}"
  labels = {
    app         = "gamira"
    environment = var.environment
    managed_by  = "terraform"
  }
}

# Every API a resource below actually uses. Enabling these is itself an
# infrastructure change worth tracking in version control rather than a
# console click nobody remembers making.
resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "sql-component.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "vpcaccess.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
