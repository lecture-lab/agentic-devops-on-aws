# Section 5-6 (Observability -> Real Alerting): the smallest real pipeline
# that proves the pattern. SNS fan-out to Telegram/Email happens outside
# Terraform for First Release (see notifications/) -- this wires the part
# that must be reliable: metric -> alarm -> notification topic.

resource "aws_sns_topic" "alerts" {
  name = "agentic-devops-dev-alerts"

  tags = {
    Name = "agentic-devops-dev-alerts"
  }
}

resource "aws_cloudwatch_metric_alarm" "high_5xx" {
  alarm_name          = "agentic-devops-dev-high-5xx"
  alarm_description   = "Target-level HTTP 5xx responses behind the ALB in a 1-minute window."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 1
  treat_missing_data  = "notBreaching"

  metric_name = "HTTPCode_Target_5XX_Count"
  namespace   = "AWS/ApplicationELB"
  statistic   = "Sum"
  period      = 60

  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "agentic-devops-dev-high-5xx"
  }
}
