terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state until a remote backend exists. Before the first real apply,
  # create a versioned GCS bucket for state (outside Terraform, so state has
  # somewhere to live before Terraform manages anything) and uncomment:
  #
  # backend "gcs" {
  #   bucket = "gamira-terraform-state-staging"
  #   prefix = "staging"
  # }
}
