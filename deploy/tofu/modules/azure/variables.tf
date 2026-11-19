variable "name" {
  description = "Prefix for every resource, e.g. nexiqon-prod."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Lowercase letters, digits and dashes (3-31 characters)."
  }
}

variable "location" {
  description = "Azure region, e.g. westeurope. Data stays in this region."
  type        = string
}

variable "vnet_cidr" {
  type    = string
  default = "10.50.0.0/16"
}

variable "kubernetes_version" {
  description = "AKS version prefix, e.g. 1.33 (patches follow the upgrade channel)."
  type        = string
  default     = "1.33"
}

variable "node_vm_size" {
  type    = string
  default = "Standard_D4s_v5"
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

variable "gpu_vm_size" {
  description = "GPU VM size for self-hosted models, e.g. Standard_NC4as_T4_v3 (empty: no GPU pool)."
  type        = string
  default     = ""
}

variable "gpu_node_count" {
  type    = number
  default = 1
}

variable "postgres_sku" {
  type    = string
  default = "GP_Standard_D2ds_v5"
}

variable "postgres_storage_mb" {
  type    = number
  default = 131072
}

variable "postgres_high_availability" {
  description = "A zone-redundant standby."
  type        = bool
  default     = false
}

variable "redis_sku" {
  description = "Azure Managed Redis SKU (Azure has no managed Valkey; the protocol is the same)."
  type        = string
  default     = "Balanced_B1"
}

variable "storage_account" {
  description = "Storage account for original files (globally unique, 3-24 lowercase letters and digits)."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account))
    error_message = "3-24 lowercase letters and digits."
  }
}

variable "create_registry" {
  description = "Create an Azure Container Registry (name: the prefix without dashes)."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = { part-of = "nexiqon" }
}
