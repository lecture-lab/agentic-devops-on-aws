# Internet-facing entry layer: ALB in the public subnets, HTTP listener,
# target group for the ECS service. HTTPS/ACM is a later extension
# (ADR-001), not implemented here.
#
# --- Recurring-cost resources in this environment (AGENTS.md §7) ---
# - aws_lb.app                    ALB: hourly charge + LCU usage
# - aws_ecs_service.app           2x Fargate tasks (256 CPU / 512 MB): hourly vCPU+GB charge
# - aws_db_instance.main          RDS db.t4g.micro + 20 GiB gp3: hourly instance + storage charge
# - aws_nat_gateway.main (nat.tf) NAT Gateway: hourly charge + per-GB data processing
#                                 (the single largest recurring cost added by this stack)
# All other resources here (subnets, security groups, IAM role, ECS
# cluster/task definition, CloudWatch log group, route table) are free
# or negligible-cost.
#
# --- Cleanup / teardown ---
# Everything in this file set lives in infra/environments/dev and is
# managed by Terraform state in this same directory. To tear it all down:
#   cd infra/environments/dev
#   terraform plan -destroy      # review first
#   terraform destroy            # requires the same human approval as
#                                 # apply; not run by this agent.
# There is no manual cleanup step outside Terraform -- no snapshots are
# kept (skip_final_snapshot = true) and no data is expected to persist.

resource "aws_lb" "app" {
  name               = "agentic-devops-dev-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  tags = {
    Name = "agentic-devops-dev-alb"
  }
}

resource "aws_lb_target_group" "app" {
  name        = "agentic-devops-dev-app-tg"
  port        = var.container_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # required for Fargate awsvpc network mode

  health_check {
    path                = "/"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "agentic-devops-dev-app-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
