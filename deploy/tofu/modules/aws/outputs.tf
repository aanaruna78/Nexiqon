output "cluster_name" {
  description = "aws eks update-kubeconfig --name <this>"
  value       = aws_eks_cluster.this.name
}

# Values for the chart's Secrets (nexiqon-database: url, migrationUrl). Private network hosts.
output "database_url" {
  description = "Application role (Secret nexiqon-database, key url). Create the role first: app_role_sql."
  value = format(
    "postgresql+asyncpg://nexiqon_app:%s@%s:%d/nexiqon?ssl=require",
    random_password.app.result, aws_db_instance.postgres.address, aws_db_instance.postgres.port,
  )
  sensitive = true
}

output "database_migration_url" {
  description = "Owner role (Secret nexiqon-database, key migrationUrl)."
  value = format(
    "postgresql+asyncpg://nexiqon:%s@%s:%d/nexiqon?ssl=require",
    random_password.owner.result, aws_db_instance.postgres.address, aws_db_instance.postgres.port,
  )
  sensitive = true
}

output "app_role_sql" {
  description = "Run once as the owner (psql \"$migrationUrl\"): the application role, which owns no tables."
  value       = "CREATE ROLE nexiqon_app LOGIN PASSWORD '${random_password.app.result}'; GRANT CONNECT ON DATABASE nexiqon TO nexiqon_app;"
  sensitive   = true
}

output "valkey_uri" {
  value     = "rediss://${aws_elasticache_replication_group.valkey.primary_endpoint_address}:6379"
  sensitive = true
}

output "bucket" {
  value = aws_s3_bucket.files.bucket
}

output "bucket_endpoint" {
  value = "https://s3.${aws_s3_bucket.files.region}.amazonaws.com"
}

output "registry_endpoint" {
  value = var.create_registry ? split("/", aws_ecr_repository.images["platform"].repository_url)[0] : null
}
