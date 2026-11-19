# Azure deployment (DV-03b), the same shape as modules/digitalocean: private network, AKS,
# PostgreSQL Flexible Server with pgvector, Azure Managed Redis and a Blob Storage container
# (the platform's `azure` blob backend; Azure Blob does not speak S3).

resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = var.tags
}

# ---------------------------------------------------------------- network

resource "azurerm_virtual_network" "this" {
  name                = "${var.name}-vnet"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = [var.vnet_cidr]
  tags                = var.tags
}

resource "azurerm_subnet" "nodes" {
  name                 = "nodes"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 4, 0)]
  service_endpoint {
    service = "Microsoft.Storage"
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 8, 255)]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.name}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                = "${var.name}-postgres"
  private_dns_zone_id = azurerm_private_dns_zone.postgres.id
  virtual_network_id  = azurerm_virtual_network.this.id
}

# ---------------------------------------------------------------- Kubernetes (AKS)

resource "azurerm_kubernetes_cluster" "this" {
  name                      = var.name
  location                  = var.location
  resource_group_name       = azurerm_resource_group.this.name
  dns_prefix                = var.name
  kubernetes_version        = var.kubernetes_version
  sku_tier                  = var.node_count >= 3 ? "Standard" : "Free"
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  local_account_disabled    = false
  tags                      = var.tags

  default_node_pool {
    name                 = "general"
    vm_size              = var.node_vm_size
    vnet_subnet_id       = azurerm_subnet.nodes.id
    auto_scaling_enabled = true
    min_count            = var.node_count
    max_count            = var.node_max
    node_labels          = { "nexiqon.dev/pool" = "general" }
    upgrade_settings {
      max_surge = "33%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "cilium"
    network_data_plane  = "cilium"
  }

  node_provisioning_profile {
    mode = "Manual"
  }

  maintenance_window_auto_upgrade {
    frequency   = "Weekly"
    interval    = 1
    day_of_week = "Sunday"
    start_time  = "02:00"
    duration    = 4
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  count                 = var.gpu_vm_size == "" ? 0 : 1
  name                  = "gpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.gpu_vm_size
  node_count            = var.gpu_node_count
  vnet_subnet_id        = azurerm_subnet.nodes.id
  node_labels           = { "nexiqon.dev/pool" = "gpu" }
  node_taints           = ["nvidia.com/gpu=present:NoSchedule"]
  tags                  = var.tags
}

# ---------------------------------------------------------------- PostgreSQL (pgvector)

resource "random_password" "owner" {
  length  = 32
  special = false
}

# The application role is created once with SQL (output app_role_sql): it must not own tables, so
# FORCE ROW LEVEL SECURITY applies to it (ADR 0005).
resource "random_password" "app" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "${var.name}-pg"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.this.name
  version                       = "16"
  sku_name                      = var.postgres_sku
  storage_mb                    = var.postgres_storage_mb
  auto_grow_enabled             = true
  backup_retention_days         = 14
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  administrator_login           = "nexiqon"
  administrator_password        = random_password.owner.result
  tags                          = var.tags

  dynamic "high_availability" {
    for_each = var.postgres_high_availability ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }

  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

# The retrieval migration creates these; Azure allows only listed extensions.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "VECTOR,LTREE"
}

resource "azurerm_postgresql_flexible_server_configuration" "tls" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "on"
}

resource "azurerm_postgresql_flexible_server_database" "nexiqon" {
  name      = "nexiqon"
  server_id = azurerm_postgresql_flexible_server.this.id
}

# ---------------------------------------------------------------- cache

resource "azurerm_managed_redis" "this" {
  name                      = "${var.name}-cache"
  location                  = var.location
  resource_group_name       = azurerm_resource_group.this.name
  sku_name                  = var.redis_sku
  high_availability_enabled = true
  tags                      = var.tags

  default_database {
    client_protocol                    = "Encrypted"
    access_keys_authentication_enabled = true
  }
}

# ---------------------------------------------------------------- object storage and images

resource "azurerm_storage_account" "files" {
  name                            = var.storage_account
  location                        = var.location
  resource_group_name             = azurerm_resource_group.this.name
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  tags                            = var.tags

  blob_properties {
    versioning_enabled = true
  }

  network_rules {
    default_action             = "Deny"
    virtual_network_subnet_ids = [azurerm_subnet.nodes.id]
    bypass                     = ["AzureServices"]
  }
}

resource "azurerm_storage_container" "files" {
  name                  = "nexiqon"
  storage_account_id    = azurerm_storage_account.files.id
  container_access_type = "private"
}

resource "azurerm_container_registry" "this" {
  count               = var.create_registry ? 1 : 0
  name                = replace(var.name, "-", "")
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  admin_enabled       = false
  tags                = var.tags
}

resource "azurerm_role_assignment" "pull" {
  count                = var.create_registry ? 1 : 0
  scope                = azurerm_container_registry.this[0].id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}
