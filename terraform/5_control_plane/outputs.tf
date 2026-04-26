output "api_endpoint" {
  description = "HTTPS base URL for the control plane"
  value       = aws_apigatewayv2_api.control_plane.api_endpoint
}

output "function_name" {
  value = aws_lambda_function.control_plane.function_name
}
