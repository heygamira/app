# docs/ANDROID_AND_CLOUD.md deployment sequence step 10 and the API address
# table (api-staging.gamira.online). Optional and off by default: domain
# mapping requires the domain to already be verified for this project in
# Search Console first (https://search.google.com/search-console — a manual,
# one-time step Terraform cannot do), and this resource will fail to create
# until that's done. Set custom_domain once verification is complete.

variable "custom_domain" {
  description = "e.g. api-staging.gamira.online. Leave empty to skip domain mapping and use the plain Cloud Run URL (outputs.api_url) instead."
  type        = string
  default     = ""
}

resource "google_cloud_run_domain_mapping" "api" {
  count    = var.custom_domain != "" ? 1 : 0
  name     = var.custom_domain
  project  = var.project_id
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.api.name
  }
}

output "domain_mapping_dns_records" {
  description = "Create these records at your DNS provider once this resource exists — Cloud Run does not do this for you."
  value       = var.custom_domain != "" ? google_cloud_run_domain_mapping.api[0].status : null
}
