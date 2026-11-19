terraform {
  required_version = ">= 1.8.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.12.0" # exact pin, older than two weeks
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
}
