# SNS -> Lambda -> Telegram, the last hop of Section 6.
#
# Deliberately does NOT manage the secret's *value* here. Terraform state
# is not a safe place for a live bot token (we proved this ourselves
# today with terraform show -json on an RDS password -- sensitive values
# come back in plaintext in the JSON plan/state, only the CLI's human
# output masks them). This resource only creates the named container;
# the value is set once, out-of-band, through the AWS Console on a
# trusted device -- not from this shared host. We tried a stdin-piped
# CLI script instead and the security review caught that it still wrote the
# value to a temp file on a UID shared with every other user, which
# mode 0600 does not actually isolate; there is no CLI/script path from
# this host that's been reviewed as safe, so there isn't one here.

variable "telegram_chat_id" {
  # Review finding F6 classification, recorded explicitly rather than left implicit:
  # a chat id is an addressing detail, not a credential -- it grants no
  # access on its own and is useless without the bot token, which is the
  # one thing this design keeps out of Terraform entirely. Accepted risk:
  # it does enter this resource's Terraform state and the Lambda's plain
  # (non-encrypted-at-rest-by-Terraform) environment variables. Kept out
  # of the committed repo anyway, on general principle -- set via
  # terraform.tfvars (gitignored), not hardcoded here.
  description = "Telegram chat id the bot posts alerts to."
  type        = string
  default     = ""
}

variable "telegram_alerts_enabled" {
  # Review finding A3: SNS retries failed/throttled Lambda deliveries for a long
  # time (days, per AWS docs on SNS delivery retries), so un-throttling
  # this function is not by itself safe -- stale queued events could
  # still fire. Default false: the handler's should_send() refuses to
  # even fetch the secret unless this is explicitly true.
  description = "Master kill switch. Must be explicitly set true for a deliberate, bounded test/live window."
  type        = bool
  default     = false
}

variable "telegram_alerts_enabled_after_epoch" {
  # Left empty by default -- the handler treats an unparsable/empty value
  # as +infinity, which means every event looks "older than the cutoff"
  # and is refused. Set to the actual current epoch time only at the
  # moment of a deliberate, authorized test/live window, so any event
  # already in SNS's retry queue from before that moment is rejected.
  description = "Unix epoch seconds. Events whose SNS publish timestamp is earlier are refused. Empty = block everything."
  type        = string
  default     = ""
}

resource "aws_secretsmanager_secret" "telegram_bot_token" {
  name                    = "agentic-devops-dev/telegram-bot-token"
  description             = "Bot token for the Section 6 infra-alerts Telegram bot. Value set out-of-band, never via Terraform."
  recovery_window_in_days = 0

  tags = {
    Name = "agentic-devops-dev-telegram-bot-token"
  }
}

data "archive_file" "telegram_lambda" {
  type        = "zip"
  source_file = "${path.module}/../../../notifications/telegram/handler.py"
  output_path = "${path.module}/.build/telegram-handler.zip"
}

resource "aws_iam_role" "telegram_lambda" {
  name = "agentic-devops-dev-telegram-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "telegram_lambda" {
  name = "agentic-devops-dev-telegram-lambda-policy"
  role = aws_iam_role.telegram_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.telegram_bot_token.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/agentic-devops-dev-telegram-alerts*"
      }
    ]
  })
}

resource "aws_lambda_function" "telegram_alerts" {
  function_name = "agentic-devops-dev-telegram-alerts"
  role          = aws_iam_role.telegram_lambda.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 10

  # Tied directly to the same kill switch as the code-level gate
  # (should_send() in handler.py), on purpose -- an earlier code-only
  # deploy (this repo's own history) silently reset a manually-set
  # `aws lambda put-function-concurrency ... 0` back to unreserved,
  # because nothing in this resource's config was managing that
  # attribute. Making it Terraform-managed and variable-driven means
  # every apply reasserts the intended state instead of silently
  # dropping an out-of-band setting. -1 = unreserved/no limit.
  reserved_concurrent_executions = var.telegram_alerts_enabled ? -1 : 0

  filename         = data.archive_file.telegram_lambda.output_path
  source_code_hash = data.archive_file.telegram_lambda.output_base64sha256

  environment {
    variables = {
      TELEGRAM_BOT_TOKEN_SECRET_ARN = aws_secretsmanager_secret.telegram_bot_token.arn
      TELEGRAM_CHAT_ID              = var.telegram_chat_id
      ALERTS_ENABLED                = tostring(var.telegram_alerts_enabled)
      ALERTS_ENABLED_AFTER_EPOCH    = var.telegram_alerts_enabled_after_epoch
    }
  }

  tags = {
    Name = "agentic-devops-dev-telegram-alerts"
  }
}

resource "aws_lambda_permission" "sns_invoke" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.telegram_alerts.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

resource "aws_sns_topic_subscription" "telegram" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.telegram_alerts.arn
}
