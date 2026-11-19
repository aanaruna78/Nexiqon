output "cluster_id" {
  value = digitalocean_kubernetes_cluster.this.id
}

output "kubeconfig" {
  description = "Cluster credentials (short-lived token)."
  value       = digitalocean_kubernetes_cluster.this.kube_config[0].raw_config
  sensitive   = true
}

# Values for the chart's Secrets (nexiqon-database: url, migrationUrl). Private network hosts.
output "database_url" {
  description = "Application role, through the connection pool (Secret nexiqon-database, key url)."
  value = format(
    "postgresql+asyncpg://%s:%s@%s:%d/%s?ssl=require",
    digitalocean_database_user.app.name,
    digitalocean_database_user.app.password,
    digitalocean_database_connection_pool.app.private_host,
    digitalocean_database_connection_pool.app.port,
    digitalocean_database_connection_pool.app.name,
  )
  sensitive = true
}

output "database_migration_url" {
  description = "Owner role, direct (Secret nexiqon-database, key migrationUrl)."
  value = format(
    "postgresql+asyncpg://%s:%s@%s:%d/%s?ssl=require",
    digitalocean_database_user.owner.name,
    digitalocean_database_user.owner.password,
    digitalocean_database_cluster.postgres.private_host,
    digitalocean_database_cluster.postgres.port,
    digitalocean_database_db.nexiqon.name,
  )
  sensitive = true
}

output "valkey_uri" {
  value     = digitalocean_database_cluster.valkey.private_uri
  sensitive = true
}

output "spaces_endpoint" {
  value = "https://${var.region}.digitaloceanspaces.com"
}

output "spaces_bucket" {
  value = digitalocean_spaces_bucket.files.name
}

output "registry_endpoint" {
  value = var.create_registry ? digitalocean_container_registry.this[0].endpoint : null
}
