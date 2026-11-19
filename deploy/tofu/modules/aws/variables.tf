variable "name" {
  description = "Prefix for every resource, e.g. nexiqon-prod."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Lowercase letters, digits and dashes (3-31 characters)."
  }
}

variable "vpc_cidr" {
  description = "Private network for the cluster and databases (two private and two public subnets are carved from it)."
  type        = string
  default     = "10.30.0.0/16"
}

variable "kubernetes_version" {
  type    = string
  default = "1.33"
}

variable "node_instance_type" {
  type    = string
  default = "m7i.xlarge"
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

variable "gpu_instance_type" {
  description = "GPU instance type for self-hosted models, e.g. g6.xlarge (empty: no GPU pool)."
  type        = string
  default     = ""
}

variable "gpu_node_count" {
  type    = number
  default = 1
}

variable "postgres_instance_class" {
  type    = string
  default = "db.m7g.large"
}

variable "postgres_storage_gb" {
  type    = number
  default = 100
}

variable "postgres_multi_az" {
  description = "A standby in a second zone (high availability)."
  type        = bool
  default     = false
}

variable "valkey_node_type" {
  type    = string
  default = "cache.t4g.medium"
}

variable "bucket" {
  description = "Bucket for original files (globally unique)."
  type        = string
}

variable "create_registry" {
  description = "Create ECR repositories for the platform and Studio images."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = { "app.kubernetes.io/part-of" = "nexiqon" }
}
