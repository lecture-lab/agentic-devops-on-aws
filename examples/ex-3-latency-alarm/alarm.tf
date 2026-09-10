# EX-3 reference (syntax-validated 2026-09-10 via `terraform fmt`/`validate`
# against the real course-repo dev config -- not deployed, see README.md).
# Same shape as infra/environments/dev/alarms.tf's high_5xx alarm, same SNS
# topic reused, different metric/statistic.
resource "aws_cloudwatch_metric_alarm" "high_latency" {
  alarm_name          = "agentic-devops-dev-high-latency-p99"
  alarm_description   = "ALB target p99 response time over 2s in a 1-minute window."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 2
  treat_missing_data  = "notBreaching"

  metric_name        = "TargetResponseTime"
  namespace          = "AWS/ApplicationELB"
  extended_statistic = "p99"
  period             = 60

  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "agentic-devops-dev-high-latency-p99"
  }
}
