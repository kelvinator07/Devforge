terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# Use the default VPC + its public subnets for v1. (v2: move to dedicated VPC.)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ========================================
# ECS cluster
# ========================================
resource "aws_ecs_cluster" "worker" {
  name = "devforge-worker"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# ========================================
# CloudWatch log group
# ========================================
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/ecs/devforge-worker"
  retention_in_days = 7
}

# ========================================
# Task execution role — ECS uses this to pull from ECR + write logs.
# ========================================
resource "aws_iam_role" "task_execution" {
  name = "devforge-worker-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ========================================
# Task role — the application's identity at runtime.
# Scopes: read OpenRouter + GitHub App secrets, invoke SageMaker, read the ingest API.
# ========================================
resource "aws_iam_role" "task" {
  name = "devforge-worker-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Attach the shared secret-read policy produced by 1_permissions.
resource "aws_iam_role_policy_attachment" "task_secret_read" {
  role       = aws_iam_role.task.name
  policy_arn = var.secret_read_policy_arn
}

resource "aws_iam_role_policy" "task_inline" {
  name = "devforge-worker-task-inline"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${data.aws_caller_identity.current.account_id}:endpoint/devforge-embedding-endpoint"
      },
      {
        Effect = "Allow"
        Action = [
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
          "s3vectors:PutVectors",
        ]
        Resource = "arn:aws:s3vectors:${var.aws_region}:${data.aws_caller_identity.current.account_id}:bucket/devforge-vectors-*/index/*"
      },
    ]
  })
}

# ========================================
# Security group — port-443-only egress allowlist (v1).
# v2: replace with AWS Network Firewall for DNS-based hostname allowlisting.
# ========================================
resource "aws_security_group" "worker" {
  name        = "devforge-worker-egress"
  description = "DevForge worker - 443-only egress (blocks attacker.com:80 demo)"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_egress_rule" "https_out" {
  security_group_id = aws_security_group.worker.id
  description       = "HTTPS to OpenRouter, GitHub, ECR, SageMaker, PyPI"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# No HTTP (80), no other ports — attacker.com on 80 is blocked.

# ========================================
# Task definition (0.5 vCPU, 1 GB — plenty for Day-2 smoke)
# ========================================
resource "aws_ecs_task_definition" "worker" {
  family                   = "devforge-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${var.ecr_repository_uri}:${var.image_tag}"
    essential = true

    environment = [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "DEVFORGE_WORKER_MODE", value = "smoke" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}
