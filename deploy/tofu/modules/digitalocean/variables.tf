variable "name" {
  description = "Prefix for every resource, e.g. nexiqon-staging."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Lowercase letters, digits and dashes (3-31 characters)."
  }
}

variable "region" {
  description = "DigitalOcean region slug, e.g. fra1, ams3, nyc3, blr1. Data stays in this region."
  type        = string
}

variable "vpc_ip_range" {
  description = "Private network for the cluster and databases."
  type        = string
  default     = "10.20.0.0/16"
}

variable "kubernetes_version_prefix" {
  description = "Latest DOKS release with this prefix is used, e.g. \"1.33.\"."
  type        = string
  default     = "1.33."
}

variable "node_size" {
  description = "Droplet size of the general node pool."
  type        = string
  default     = "s-4vcpu-8gb"
}

variable "node_count" {
  description = "Minimum nodes in the general pool (it autoscales up to node_max)."
  type        = number
  default     = 3
}

variable "node_max" {
  type    = number
  default = 6
}

variable "gpu_node_size" {
  description = "GPU Droplet size for self-hosted models (empty: no GPU pool). See docs/guides/gpu-models.md."
  type        = string
  default     = ""
}

variable "gpu_node_count" {
  type    = number
  default = 1
}

variable "postgres_size" {
  description = "Managed PostgreSQL size. Production/HA needs an edition with standby nodes (see PLAN.md §2.1)."
  type        = string
  default     = "db-s-2vcpu-4gb"
}

variable "postgres_nodes" {
  description = "1 = primary only; 2-3 adds standby nodes (high availability)."
  type        = number
  default     = 1
}

variable "valkey_size" {
  type    = string
  default = "db-s-1vcpu-2gb"
}

variable "spaces_bucket" {
  description = "Bucket for original files (must be globally unique)."
  type        = string
}

variable "create_registry" {
  description = "Create the account's container registry (one per account)."
  type        = bool
  default     = false
}

variable "registry_tier" {
  type    = string
  default = "basic"
}

variable "tags" {
  type    = list(string)
  default = ["nexiqon"]
}
