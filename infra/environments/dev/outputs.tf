output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "app_subnet_ids" {
  description = "Application-tier private subnets (ECS Fargate tasks)."
  value       = aws_subnet.app[*].id
}

output "alb_dns_name" {
  description = "DNS name of the internet-facing ALB."
  value       = aws_lb.app.dns_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.app.name
}

output "rds_endpoint" {
  description = "RDS connection endpoint (host:port). Non-sensitive; the master password is never output."
  value       = aws_db_instance.main.endpoint
}

output "rds_address" {
  description = "RDS hostname only (non-sensitive)."
  value       = aws_db_instance.main.address
}

output "rds_port" {
  value = aws_db_instance.main.port
}
