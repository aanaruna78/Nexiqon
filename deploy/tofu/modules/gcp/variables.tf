variable "name" {
  description = "Prefix for every resource, e.g. nexiqon-prod."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Lowercase letters, digits and dashes (3-31 characters)."
  }
}

variable "project" {
  description = "Google Cloud project id."
  type        = string
}

variable "region" {
  description = "Region, e.g. europe-west3. Data stays in this region."
  type        = string
}

variable "subnet_cidr" {
  type    = string
  default = "10.40.0.0/20"
}

variable "pods_cidr" {
  type    = string
  default = "10.44.0.0/14"
}

variable "services_cidr" {
  type    = string
  default = "10.48.0.0/20"
}

variable "node_machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "node_count" {
  description = "Minimum nodes per zone in the general pool (it autoscales up to node_max)."
  type        = number
  default     = 1
}

variable "node_max" {
  type    = number
  default = 3
}

variable "gpu_machine_type" {
  description = "Machine type for self-hosted models, e.g. g2-standard-8 (empty: no GPU pool)."
  type        = string
  default     = ""
}

variable "gpu_type" {
  type    = string
  default = "nvidia-l4"
}

variable "gpu_node_count" {
  type    = number
  default = 1
}

variable "postgres_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "postgres_high_availability" {
  description = "A standby in a second zone (REGIONAL availability)."
  type        = bool
  default     = false
}

variable "valkey_shards" {
  type    = number
  default = 1
}

variable "bucket" {
  description = "Bucket for original files (globally unique)."
  type        = string
}

variable "create_registry" {
  description = "Create an Artifact Registry repository for the images."
  type        = bool
  default     = false
}

variable "labels" {
  type    = map(string)
  default = { part-of = "nexiqon" }
}
