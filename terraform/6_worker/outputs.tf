output "cluster_name" {
  value = aws_ecs_cluster.worker.name
}

output "cluster_arn" {
  value = aws_ecs_cluster.worker.arn
}

output "task_definition_family" {
  value = aws_ecs_task_definition.worker.family
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.worker.arn
}

output "subnet_ids" {
  description = "Default-VPC subnets to launch the Fargate task in"
  value       = data.aws_subnets.default.ids
}

output "security_group_id" {
  value = aws_security_group.worker.id
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.worker.name
}

output "run_task_instructions" {
  value = <<-EOT

    To run a Fargate task:

    SUBNET=$(terraform output -json subnet_ids | jq -r '.[0]')
    SG=$(terraform output -raw security_group_id)

    aws ecs run-task \
      --cluster devforge-worker \
      --task-definition devforge-worker \
      --launch-type FARGATE \
      --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}" \
      --region us-east-1

    Tail logs:
      aws logs tail /aws/ecs/devforge-worker --follow --region us-east-1

    Negative probe (expects egress-block):
      aws ecs run-task ... --overrides '{"containerOverrides":[{"name":"worker","environment":[{"name":"DEVFORGE_WORKER_MODE","value":"attacker"}]}]}'
  EOT
}
