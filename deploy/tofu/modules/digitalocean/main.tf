# DigitalOcean reference deployment (DV-03, ADR 0014). Everything Nexiqon needs outside the Helm
# chart: private network, Kubernetes, PostgreSQL with pgvector, Valkey and object storage. NATS,
# Temporal and the IdP run in the cluster or as separate services; the chart references them.

resource "digitalocean_vpc" "this" {
  name     = "${var.name}-vpc"
  region   = var.region
  ip_range = var.vpc_ip_range
}

data "digitalocean_kubernetes_versions" "this" {
  version_prefix = var.kubernetes_version_prefix
}

resource "digitalocean_kubernetes_cluster" "this" {
  name          = var.name
  region        = var.region
  version       = data.digitalocean_kubernetes_versions.this.latest_version
  vpc_uuid      = digitalocean_vpc.this.id
  auto_upgrade  = true
  surge_upgrade = true
  ha            = var.node_count >= 3
  tags          = var.tags

  maintenance_policy {
    day        = "sunday"
    start_time = "02:00"
  }

  node_pool {
    name       = "general"
    size       = var.node_size
    auto_scale = true
    min_nodes  = var.node_count
    max_nodes  = var.node_max
    labels     = { "nexiqon.dev/pool" = "general" }
  }
}

resource "digitalocean_kubernetes_node_pool" "gpu" {
  count      = var.gpu_node_size == "" ? 0 : 1
  cluster_id = digitalocean_kubernetes_cluster.this.id
  name       = "gpu"
  size       = var.gpu_node_size
  node_count = var.gpu_node_count
  labels     = { "nexiqon.dev/pool" = "gpu" }
  taint {
    key    = "nvidia.com/gpu"
    value  = "present"
    effect = "NoSchedule"
  }
}

# ---------------------------------------------------------------- PostgreSQL (pgvector)

resource "digitalocean_database_cluster" "postgres" {
  name                 = "${var.name}-pg"
  engine               = "pg"
  version              = "16"
  size                 = var.postgres_size
  region               = var.region
  node_count           = var.postgres_nodes
  private_network_uuid = digitalocean_vpc.this.id
  tags                 = var.tags
}

resource "digitalocean_database_db" "nexiqon" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "nexiqon"
}

# Owner of the schemas (migrations) and the application role. The application role does not own
# tables, so FORCE ROW LEVEL SECURITY applies to it (ADR 0005).
resource "digitalocean_database_user" "owner" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "nexiqon"
}

resource "digitalocean_database_user" "app" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "nexiqon_app"
}

resource "digitalocean_database_connection_pool" "app" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "nexiqon-app"
  mode       = "transaction"
  size       = 20
  db_name    = digitalocean_database_db.nexiqon.name
  user       = digitalocean_database_user.app.name
}

resource "digitalocean_database_firewall" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id
  rule {
    type  = "k8s"
    value = digitalocean_kubernetes_cluster.this.id
  }
}

# ---------------------------------------------------------------- Valkey

resource "digitalocean_database_cluster" "valkey" {
  name                 = "${var.name}-valkey"
  engine               = "valkey"
  version              = "8"
  size                 = var.valkey_size
  region               = var.region
  node_count           = 1
  private_network_uuid = digitalocean_vpc.this.id
  tags                 = var.tags
}

resource "digitalocean_database_firewall" "valkey" {
  cluster_id = digitalocean_database_cluster.valkey.id
  rule {
    type  = "k8s"
    value = digitalocean_kubernetes_cluster.this.id
  }
}

# ---------------------------------------------------------------- object storage and images

resource "digitalocean_spaces_bucket" "files" {
  name   = var.spaces_bucket
  region = var.region
  acl    = "private"

  versioning {
    enabled = true
  }
}

resource "digitalocean_container_registry" "this" {
  count                  = var.create_registry ? 1 : 0
  name                   = var.name
  subscription_tier_slug = var.registry_tier
  region                 = var.region
}
