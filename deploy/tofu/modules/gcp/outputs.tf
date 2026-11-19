output "cluster_name" {
  description = "gcloud container clusters get-credentials <this> --region <region>"
  value       = google_container_cluster.this.name
}

# Values for the chart's Secrets (nexiqon-database: url, migrationUrl). Private addresses.
output "database_url" {
  description = "Application role (Secret nexiqon-database, key url)."
  value = format(
    "postgresql+asyncpg://%s:%s@%s:5432/%s?ssl=require",
    google_sql_user.app.name, random_password.app.result,
    google_sql_database_instance.postgres.private_ip_address, google_sql_database.nexiqon.name,
  )
  sensitive = true
}

output "database_migration_url" {
  description = "Owner role (Secret nexiqon-database, key migrationUrl)."
  value = format(
    "postgresql+asyncpg://%s:%s@%s:5432/%s?ssl=require",
    google_sql_user.owner.name, random_password.owner.result,
    google_sql_database_instance.postgres.private_ip_address, google_sql_database.nexiqon.name,
  )
  sensitive = true
}

output "app_role_sql" {
  description = "Cloud SQL creates both roles; run once as the owner so the application role may connect."
  value       = "GRANT CONNECT ON DATABASE nexiqon TO nexiqon_app;"
}

output "valkey_uri" {
  value = format(
    "rediss://%s:%d",
    google_memorystore_instance.valkey.endpoints[0].connections[0].psc_auto_connection[0].ip_address,
    google_memorystore_instance.valkey.endpoints[0].connections[0].psc_auto_connection[0].port,
  )
  sensitive = true
}

output "bucket" {
  value = google_storage_bucket.files.name
}

output "bucket_endpoint" {
  description = "S3-compatible endpoint (HMAC keys for a service account)."
  value       = "https://storage.googleapis.com"
}

output "registry_endpoint" {
  value = var.create_registry ? "${var.region}-docker.pkg.dev/${var.project}/${var.name}" : null
}
