variable "project_id" {
  description = "The GCP project this stack deploys into. One project per environment (staging, production) — see docs/ANDROID_AND_CLOUD.md: 'Do not rely on resource-name prefixes inside one project as the only isolation boundary.'"
  type        = string
}

variable "region" {
  description = "GCP region for every regional resource. Pick one supporting Cloud Run, Cloud SQL and Secret Manager, and document data residency alongside this choice per docs/ANDROID_AND_CLOUD.md."
  type        = string
  default     = "asia-south1"
}

variable "environment" {
  description = "Short environment name, used in resource names and labels. \"staging\" or \"production\" — never deploy production from this same state without changing project_id too."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be \"staging\" or \"production\"."
  }
}

variable "backend_image" {
  description = "Full Artifact Registry image reference for the backend container, e.g. REGION-docker.pkg.dev/PROJECT/gamira/backend:TAG. Left as a placeholder here; the deploy pipeline supplies the real tag per release, matching docs/ANDROID_AND_CLOUD.md's 'Promote an immutable build to production' — never :latest."
  type        = string
  default     = "gcr.io/cloudrun/hello" # placeholder until the first real image is pushed
}

variable "cors_origins" {
  description = "Comma-separated origins the API accepts credentialed requests from — the Family Dashboard and (once packaged) the Android apps' origins. Never \"*\"."
  type        = string
}

variable "firebase_project_id" {
  description = "The Firebase project backing AUTH_MODE=firebase. Must be a project of its own for staging, separate from any local-dev Firebase project."
  type        = string
}

variable "gemini_api_key" {
  description = "Server-side Gemini API key. Stored in Secret Manager, never in state or a .tfvars file committed to git — pass via TF_VAR_gemini_api_key or an untracked *.auto.tfvars file."
  type        = string
  sensitive   = true
}

variable "fcm_credentials_json" {
  description = "The Firebase service-account key (JSON, as a string) used for FCM HTTP v1 delivery. Same handling as gemini_api_key: never committed, passed via environment or an untracked tfvars file."
  type        = string
  sensitive   = true
}

variable "db_tier" {
  description = "Cloud SQL machine tier. Small on purpose for staging — docs/ANDROID_AND_CLOUD.md calls for a 'Small Cloud SQL PostgreSQL instance' there; size up only after staging proves the load."
  type        = string
  default     = "db-custom-1-3840"
}

variable "db_availability_type" {
  description = "ZONAL for staging (cheaper, no cross-zone failover); REGIONAL for production."
  type        = string
  default     = "ZONAL"
}

variable "api_max_instances" {
  description = "Cloud Run max instance count for the API service. Bounded against Cloud SQL's connection limit: each instance can open up to (database_pool_size + database_max_overflow) = 30 connections (app/core/config.py), so this must stay comfortably under the chosen db_tier's max_connections. Verify the actual limit for db_tier before raising this — Cloud SQL sets it from instance memory, not a fixed number."
  type        = number
  default     = 3
}

variable "worker_min_instances" {
  description = "The worker is a long-running poller, not a request-driven service — it needs at least one instance always up to process the job queue, or nothing scheduled (dose reminders, SOS escalation, notification retries) ever runs. See gamira-backend/app/worker.py."
  type        = number
  default     = 1
}
