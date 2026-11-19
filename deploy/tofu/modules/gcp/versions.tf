terraform {
  required_version = ">= 1.8.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.9.0" # exact pin, older than two weeks
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
}
