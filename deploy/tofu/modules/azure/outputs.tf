output "cluster_name" {
  description = "az aks get-credentials --resource-group <name> --name <this>"
  value       = azurerm_kubernetes_cluster.this.name
}

# Values for the chart's Secrets (nexiqon-database: url, migrationUrl). Private addresses.
output "database_url" {
  description = "Application role (Secret nexiqon-database, key url). Create the role first: app_role_sql."
  value = format(
    "postgresql+asyncpg://nexiqon_app:%s@%s:5432/nexiqon?ssl=require",
    random_password.app.result, azurerm_postgresql_flexible_server.this.fqdn,
  )
  sensitive = true
}

output "database_migration_url" {
  description = "Owner role (Secret nexiqon-database, key migrationUrl)."
  value = format(
    "postgresql+asyncpg://nexiqon:%s@%s:5432/nexiqon?ssl=require",
    random_password.owner.result, azurerm_postgresql_flexible_server.this.fqdn,
  )
  sensitive = true
}

output "app_role_sql" {
  description = "Run once as the owner (psql \"$migrationUrl\"): the application role, which owns no tables."
  value       = "CREATE ROLE nexiqon_app LOGIN PASSWORD '${random_password.app.result}'; GRANT CONNECT ON DATABASE nexiqon TO nexiqon_app;"
  sensitive   = true
}

output "valkey_uri" {
  description = "Azure Managed Redis (same protocol as Valkey)."
  value       = "rediss://:${azurerm_managed_redis.this.default_database[0].primary_access_key}@${azurerm_managed_redis.this.hostname}:${azurerm_managed_redis.this.default_database[0].port}"
  sensitive   = true
}

# Blob settings for the chart: blobs.backend=azure, endpoint, bucket=container,
# access_key=account, secret_key=blob_account_key (Secret nexiqon-blobs).
output "blob_endpoint" {
  value = azurerm_storage_account.files.primary_blob_endpoint
}

output "bucket" {
  value = azurerm_storage_container.files.name
}

output "blob_account" {
  value = azurerm_storage_account.files.name
}

output "blob_account_key" {
  value     = azurerm_storage_account.files.primary_access_key
  sensitive = true
}

output "registry_endpoint" {
  value = var.create_registry ? azurerm_container_registry.this[0].login_server : null
}
