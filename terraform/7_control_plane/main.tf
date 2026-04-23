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

# ========================================
# CloudWatch log group
# ========================================
resource "aws_cloudwatch_log_group" "control_plane" {
  name              = "/aws/lambda/devforge-control-plane"
  retention_in_days = 7
}

# ========================================
# Lambda execution role
# ========================================
resource "aws_iam_role" "lambda" {
  name = "devforge-control-plane-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Secret read (OpenRouter + GitHub App private key) from 1_permissions
resource "aws_iam_role_policy_attachment" "lambda_secret_read" {
  role       = aws_iam_role.lambda.name
  policy_arn = var.secret_read_policy_arn
}

# Aurora Data API + credentials-secret read
resource "aws_iam_role_policy" "lambda_aurora" {
  name = "devforge-control-plane-aurora"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds-data:ExecuteStatement",
          "rds-data:BatchExecuteStatement",
          "rds-data:BeginTransaction",
          "rds-data:CommitTransaction",
          "rds-data:RollbackTransaction",
        ]
        Resource = var.aurora_cluster_arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.aurora_secret_arn
      },
    ]
  })
}

# ========================================
# Lambda function (container image)
# ========================================
resource "aws_lambda_function" "control_plane" {
  function_name = "devforge-control-plane"
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_repository_uri}:${var.image_tag}"

  timeout     = 30
  memory_size = 512

  environment {
    variables = {
      AURORA_CLUSTER_ARN = var.aurora_cluster_arn
      AURORA_SECRET_ARN  = var.aurora_secret_arn
      AURORA_DATABASE    = "devforge"
      GITHUB_APP_ID      = var.github_app_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.control_plane]
}

# ========================================
# API Gateway (HTTP API v2)
# ========================================
resource "aws_apigatewayv2_api" "control_plane" {
  name          = "devforge-control-plane"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.control_plane.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.control_plane.invoke_arn
  payload_format_version = "2.0"
  integration_method     = "POST"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.control_plane.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.control_plane.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.control_plane.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.control_plane.execution_arn}/*/*"
}
