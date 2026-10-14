# Section 5 (Observability): one CloudWatch dashboard that puts the five
# things the lecture looks at on a single screen -- Request, Latency, Errors,
# CPU, Task Health -- using the same metrics the console tour (L05-02.03) and
# the alarm (alarms.tf) already use.
#
# Off by default so the Section 4 plan stays exactly as reviewed. Turn it on
# in Section 5 with  create_dashboard = true  in terraform.tfvars and run
# plan / apply again: the plan then shows one resource to add.
#
# Nothing sensitive is in here: the dimensions are the ALB / target group
# name suffixes (no account id) and the ECS cluster / service names.

variable "create_dashboard" {
  description = "Create the Section 5 CloudWatch dashboard (one resource). Leave false until Section 5."
  type        = bool
  default     = false
}

locals {
  dashboard_name = "agentic-devops-${var.environment}-overview"
}

resource "aws_cloudwatch_dashboard" "overview" {
  count          = var.create_dashboard ? 1 : 0
  dashboard_name = local.dashboard_name

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6
        properties = {
          title   = "Request"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          stat    = "Sum"
          period  = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.app.arn_suffix]
          ]
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6
        properties = {
          title   = "Latency"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          stat    = "Average"
          period  = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.app.arn_suffix]
          ]
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6
        properties = {
          title   = "Errors"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          stat    = "Sum"
          period  = 60
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.app.arn_suffix, "TargetGroup", aws_lb_target_group.app.arn_suffix]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title   = "CPU"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          stat    = "Average"
          period  = 60
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.app.name]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title   = "Task Health"
          region  = var.aws_region
          view    = "timeSeries"
          stacked = false
          stat    = "Average"
          period  = 60
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", aws_lb.app.arn_suffix, "TargetGroup", aws_lb_target_group.app.arn_suffix],
            ["AWS/ApplicationELB", "UnHealthyHostCount", "LoadBalancer", aws_lb.app.arn_suffix, "TargetGroup", aws_lb_target_group.app.arn_suffix]
          ]
        }
      }
    ]
  })
}
