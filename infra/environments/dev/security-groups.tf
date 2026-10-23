# Security groups implementing the Internet -> ALB -> App -> DB chain
# required by ADR-001.
#
# Each SG is created bare (no inline ingress/egress blocks) and paired
# with explicit aws_vpc_security_group_ingress_rule /
# aws_vpc_security_group_egress_rule resources. This avoids the classic
# Terraform footgun where an aws_security_group with inline rule blocks
# silently replaces AWS's default "allow all egress" with "no egress" the
# moment any inline block is present, and it makes each allowed path
# self-documenting.

resource "aws_security_group" "alb" {
  name        = "agentic-devops-dev-alb-sg"
  description = "ALB: internet ingress on HTTP, egress only to the app tier"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "agentic-devops-dev-alb-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_from_internet" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from the internet"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to ECS app tier on the container port"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "app" {
  name        = "agentic-devops-dev-app-sg"
  description = "ECS Fargate tasks: ingress from ALB only, egress to DB (5432) and HTTPS (443) only"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "agentic-devops-dev-app-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  description                  = "Container port from the ALB"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_to_db" {
  security_group_id            = aws_security_group.app.id
  description                  = "Postgres to the database tier"
  referenced_security_group_id = aws_security_group.db.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_https_egress" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS via the NAT Gateway (nat.tf) for ECR image pulls and CloudWatch Logs delivery -- least-privilege: HTTPS only, not all traffic"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_security_group" "db" {
  name        = "agentic-devops-dev-db-sg"
  description = "RDS PostgreSQL: ingress from the app tier only, no internet exposure, no egress"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "agentic-devops-dev-db-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "Postgres from the app tier"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# Intentionally no egress rule for aws_security_group.db: the database
# tier does not need to initiate outbound connections.
