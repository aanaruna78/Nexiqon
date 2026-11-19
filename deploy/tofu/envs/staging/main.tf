# Staging on DigitalOcean. State lives in a Spaces bucket (S3 backend); credentials come from the
# environment: DIGITALOCEAN_TOKEN, SPACES_ACCESS_KEY_ID, SPACES_SECRET_ACCESS_KEY (and the same
# keys as AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY for the state backend).
#
#   tofu init -backend-config="bucket=<state-bucket>"
#   tofu plan -out staging.plan && tofu apply staging.plan

terraform {
  required_version = ">= 1.8.0"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "2.107.0" # exact pin, older than two weeks
    }
  }
  backend "s3" {
    key                         = "nexiqon/staging.tfstate"
    region                      = "us-east-1"
    endpoints                   = { s3 = "https://fra1.digitaloceanspaces.com" }
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_s3_checksum            = true
    use_path_style              = false
  }
}

provider "digitalocean" {}

module "nexiqon" {
  source        = "../../modules/digitalocean"
  name          = "nexiqon-staging"
  region        = "fra1"
  spaces_bucket = "nexiqon-staging-files"
  node_count    = 2
  node_max      = 4
}

output "database_url" {
  value     = module.nexiqon.database_url
  sensitive = true
}

output "database_migration_url" {
  value     = module.nexiqon.database_migration_url
  sensitive = true
}

output "kubeconfig" {
  value     = module.nexiqon.kubeconfig
  sensitive = true
}
