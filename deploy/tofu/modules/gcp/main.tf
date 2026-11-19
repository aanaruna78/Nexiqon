# Google Cloud deployment (DV-03b), the same shape as modules/digitalocean: private network, GKE,
# Cloud SQL PostgreSQL with pgvector, Memorystore for Valkey and a Cloud Storage bucket.

# ---------------------------------------------------------------- network

resource "google_compute_network" "this" {
  project                 = var.project
  name                    = "${var.name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "this" {
  project                  = var.project
  name                     = "${var.name}-nodes"
  region                   = var.region
  network                  = google_compute_network.this.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }
}

resource "google_compute_router" "this" {
  project = var.project
  name    = "${var.name}-router"
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  project                            = var.project
  name                               = "${var.name}-nat"
  router                             = google_compute_router.this.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# Private services access: Cloud SQL and Memorystore get addresses inside the network.
resource "google_compute_global_address" "services" {
  project       = var.project
  name          = "${var.name}-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.this.id
}

resource "google_service_networking_connection" "this" {
  network                 = google_compute_network.this.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.services.name]
}

# ---------------------------------------------------------------- Kubernetes (GKE)

resource "google_service_account" "nodes" {
  project      = var.project
  account_id   = "${var.name}-nodes"
  display_name = "${var.name} GKE nodes"
}

resource "google_project_iam_member" "nodes" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/artifactregistry.reader",
  ])
  project = var.project
  role    = each.value
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

resource "google_container_cluster" "this" {
  project             = var.project
  name                = var.name
  location            = var.region
  network             = google_compute_network.this.id
  subnetwork          = google_compute_subnetwork.this.id
  initial_node_count  = 0 # no default pool: the pools below
  deletion_protection = true
  resource_labels     = var.labels

  release_channel {
    channel = "REGULAR"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  workload_identity_config {
    workload_pool = "${var.project}.svc.id.goog"
  }

  network_policy {
    enabled = true
  }

  maintenance_policy {
    recurring_window {
      start_time = "2026-01-04T02:00:00Z"
      end_time   = "2026-01-04T06:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=SU"
    }
  }
}

resource "google_container_node_pool" "general" {
  project  = var.project
  name     = "general"
  cluster  = google_container_cluster.this.id
  location = var.region

  autoscaling {
    min_node_count = var.node_count
    max_node_count = var.node_max
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.node_machine_type
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = { "nexiqon.dev/pool" = "general" }
    shielded_instance_config {
      enable_secure_boot = true
    }
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}

resource "google_container_node_pool" "gpu" {
  count      = var.gpu_machine_type == "" ? 0 : 1
  project    = var.project
  name       = "gpu"
  cluster    = google_container_cluster.this.id
  location   = var.region
  node_count = var.gpu_node_count

  node_config {
    machine_type    = var.gpu_machine_type
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = { "nexiqon.dev/pool" = "gpu" }
    guest_accelerator {
      type  = var.gpu_type
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "LATEST"
      }
    }
    taint {
      key    = "nvidia.com/gpu"
      value  = "present"
      effect = "NO_SCHEDULE"
    }
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}

# ---------------------------------------------------------------- PostgreSQL (pgvector)

resource "google_sql_database_instance" "postgres" {
  project             = var.project
  name                = "${var.name}-pg"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true
  depends_on          = [google_service_networking_connection.this]

  settings {
    tier              = var.postgres_tier
    availability_type = var.postgres_high_availability ? "REGIONAL" : "ZONAL"
    user_labels       = var.labels

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.this.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = 14
      }
    }

    insights_config {
      query_insights_enabled = true
    }
  }
}

resource "google_sql_database" "nexiqon" {
  project  = var.project
  instance = google_sql_database_instance.postgres.name
  name     = "nexiqon"
}

resource "random_password" "owner" {
  length  = 32
  special = false
}

resource "random_password" "app" {
  length  = 32
  special = false
}

# Owner of the schemas (migrations) and the application role. The application role does not own
# tables, so FORCE ROW LEVEL SECURITY applies to it (ADR 0005).
resource "google_sql_user" "owner" {
  project  = var.project
  instance = google_sql_database_instance.postgres.name
  name     = "nexiqon"
  password = random_password.owner.result
}

resource "google_sql_user" "app" {
  project  = var.project
  instance = google_sql_database_instance.postgres.name
  name     = "nexiqon_app"
  password = random_password.app.result
}

# ---------------------------------------------------------------- Valkey (Memorystore)

resource "google_network_connectivity_service_connection_policy" "valkey" {
  project       = var.project
  name          = "${var.name}-valkey"
  location      = var.region
  service_class = "gcp-memorystore"
  network       = google_compute_network.this.id
  psc_config {
    subnetworks = [google_compute_subnetwork.this.id]
  }
}

resource "google_memorystore_instance" "valkey" {
  project                     = var.project
  instance_id                 = "${var.name}-valkey"
  location                    = var.region
  shard_count                 = var.valkey_shards
  engine_version              = "VALKEY_8_0"
  transit_encryption_mode     = "SERVER_AUTHENTICATION"
  deletion_protection_enabled = true
  labels                      = var.labels

  desired_auto_created_endpoints {
    network    = google_compute_network.this.id
    project_id = var.project
  }

  depends_on = [google_network_connectivity_service_connection_policy.valkey]
}

# ---------------------------------------------------------------- object storage and images

resource "google_storage_bucket" "files" {
  project                     = var.project
  name                        = var.bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = var.labels

  versioning {
    enabled = true
  }
}

resource "google_artifact_registry_repository" "images" {
  count         = var.create_registry ? 1 : 0
  project       = var.project
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  labels        = var.labels

  docker_config {
    immutable_tags = true
  }
}
