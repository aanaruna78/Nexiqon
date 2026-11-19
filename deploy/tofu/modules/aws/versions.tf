terraform {
  required_version = ">= 1.8.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0" # exact pin, older than two weeks
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
}
