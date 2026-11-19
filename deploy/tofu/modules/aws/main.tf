# AWS deployment (DV-03b), the same shape as modules/digitalocean: private network, EKS, PostgreSQL
# with pgvector (RDS), Valkey (ElastiCache) and an S3 bucket. The chart references them by Secret.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

# ---------------------------------------------------------------- network

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name}-vpc" })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone = local.zones[count.index]
  tags              = merge(var.tags, { Name = "${var.name}-private-${count.index}", "kubernetes.io/role/internal-elb" = "1" })
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index + 8)
  availability_zone       = local.zones[count.index]
  map_public_ip_on_launch = false
  tags                    = merge(var.tags, { Name = "${var.name}-public-${count.index}", "kubernetes.io/role/elb" = "1" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = var.tags
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = var.tags
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = var.tags
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = var.tags
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }
  tags = var.tags
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------- Kubernetes (EKS)

data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "node_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${var.name}-eks"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "nodes" {
  name               = "${var.name}-nodes"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "nodes" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])
  role       = aws_iam_role.nodes.name
  policy_arn = each.value
}

resource "aws_eks_cluster" "this" {
  name     = var.name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = true
  }

  access_config {
    authentication_mode = "API"
  }

  # Kubernetes Secrets encrypted with a key of this account.
  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = aws_kms_key.this.arn
    }
  }

  tags       = var.tags
  depends_on = [aws_iam_role_policy_attachment.cluster]
}

resource "aws_kms_key" "this" {
  description         = "${var.name}: Kubernetes Secrets, database and bucket encryption"
  enable_key_rotation = true
  tags                = var.tags
}

resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "general"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = aws_subnet.private[*].id
  instance_types  = [var.node_instance_type]
  labels          = { "nexiqon.dev/pool" = "general" }

  scaling_config {
    min_size     = var.node_count
    desired_size = var.node_count
    max_size     = var.node_max
  }

  update_config {
    max_unavailable = 1
  }

  tags       = var.tags
  depends_on = [aws_iam_role_policy_attachment.nodes]
}

resource "aws_eks_node_group" "gpu" {
  count           = var.gpu_instance_type == "" ? 0 : 1
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "gpu"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = aws_subnet.private[*].id
  instance_types  = [var.gpu_instance_type]
  ami_type        = "AL2023_x86_64_NVIDIA"
  labels          = { "nexiqon.dev/pool" = "gpu" }

  scaling_config {
    min_size     = var.gpu_node_count
    desired_size = var.gpu_node_count
    max_size     = var.gpu_node_count
  }

  taint {
    key    = "nvidia.com/gpu"
    value  = "present"
    effect = "NO_SCHEDULE"
  }

  tags       = var.tags
  depends_on = [aws_iam_role_policy_attachment.nodes]
}

# ---------------------------------------------------------------- PostgreSQL (pgvector)

resource "aws_security_group" "data" {
  name        = "${var.name}-data"
  description = "PostgreSQL and Valkey: from the cluster only"
  vpc_id      = aws_vpc.this.id
  tags        = var.tags
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.data.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "valkey" {
  security_group_id            = aws_security_group.data.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
  tags       = var.tags
}

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

resource "aws_db_parameter_group" "this" {
  name   = var.name
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  tags = var.tags
}

resource "aws_db_instance" "postgres" {
  identifier                   = "${var.name}-pg"
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.postgres_instance_class
  allocated_storage            = var.postgres_storage_gb
  max_allocated_storage        = var.postgres_storage_gb * 4
  storage_encrypted            = true
  kms_key_id                   = aws_kms_key.this.arn
  db_name                      = "nexiqon"
  username                     = "nexiqon"
  password                     = random_password.owner.result
  multi_az                     = var.postgres_multi_az
  db_subnet_group_name         = aws_db_subnet_group.this.name
  vpc_security_group_ids       = [aws_security_group.data.id]
  parameter_group_name         = aws_db_parameter_group.this.name
  backup_retention_period      = 14
  deletion_protection          = true
  auto_minor_version_upgrade   = true
  performance_insights_enabled = true
  skip_final_snapshot          = false
  final_snapshot_identifier    = "${var.name}-pg-final"
  tags                         = var.tags
}

# ---------------------------------------------------------------- Valkey

resource "aws_elasticache_subnet_group" "this" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id       = "${var.name}-valkey"
  description                = "Nexiqon cache"
  engine                     = "valkey"
  engine_version             = "8.0"
  node_type                  = var.valkey_node_type
  num_cache_clusters         = 1
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  tags                       = var.tags
}

# ---------------------------------------------------------------- object storage and images

resource "aws_s3_bucket" "files" {
  bucket = var.bucket
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "files" {
  bucket = aws_s3_bucket.files.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.this.arn
    }
  }
}

resource "aws_ecr_repository" "images" {
  for_each             = var.create_registry ? toset(["platform", "studio"]) : toset([])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = var.tags
}
