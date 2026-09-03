# Container compute layer: ECS cluster + Fargate service running a
# public sample image for a pipeline smoke test (not the course
# application). Registered with the ALB target group; logs to
# CloudWatch Logs.

resource "aws_ecs_cluster" "main" {
  name = "agentic-devops-dev-cluster"

  tags = {
    Name = "agentic-devops-dev-cluster"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/agentic-devops-dev-app"
  retention_in_days = 7

  tags = {
    Name = "agentic-devops-dev-app-logs"
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "agentic-devops-dev-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "agentic-devops-dev-ecs-task-execution"
  }
}

# AWS-managed policy: least-privilege role scoped to what the ECS agent
# needs to pull images and ship logs (ECR read + CloudWatch Logs write).
resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "app" {
  family                   = "agentic-devops-dev-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "app"
      image     = var.container_image
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "app"
        }
      }
    }
  ])

  tags = {
    Name = "agentic-devops-dev-app-task"
  }
}

resource "aws_ecs_service" "app" {
  name            = "agentic-devops-dev-app-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = var.container_port
  }

  # ECS requires the target group to already have a listener attached
  # before a service can register with it.
  depends_on = [aws_lb_listener.http, aws_iam_role_policy_attachment.ecs_task_execution_managed]

  tags = {
    Name = "agentic-devops-dev-app-service"
  }
}
