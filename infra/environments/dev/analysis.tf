# 알림 뒤 자동 1차 분석 (Section 6 확장).
# 알림 Lambda(telegram.tf)가 Telegram 발송에 성공한 *뒤에* 이 Lambda 를 비동기로 부른다.
# 분석은 자동이고, 승인·조치는 여전히 사람이다(Human Gate). 이 Lambda 는 읽기 전용 권한과 모델 호출 권한만 갖는다.
#
# 킬 스위치: analysis_enabled = false 이면 예약 동시성 0 (함수가 아예 실행되지 않는다). 알림 Lambda 와 같은 방식이다.
# 양수 예약 동시성(예: 1)은 쓰지 않는다 — 새 AWS 계정은 Lambda 동시성 한도가 10 이라, 예약하면 «예약 안 된 몫이 10 밑으로
# 내려간다»며 apply 가 거절된다. 대신 단일 실행·중복 차단은 DynamoDB 조건부 쓰기로 한다.

variable "analysis_enabled" {
  description = "Master kill switch for the automatic first-pass analysis. false = reserved concurrency 0 (the function cannot run)."
  type        = bool
  default     = false
}

variable "analysis_model_id" {
  description = "Bedrock inference profile ID (as of 2026-10-21). Claude Sonnet 4.6 is available in Seoul only through the global profile, so the request may be processed outside Seoul. Fallback: global.anthropic.claude-haiku-4-5-20251001-v1:0 (changing this one variable also changes the IAM resources below)."
  type        = string
  default     = "global.anthropic.claude-sonnet-4-6"
}

variable "analysis_cooldown_minutes" {
  description = "Minimum minutes between two analyses of the same alarm."
  type        = number
  default     = 15
}

variable "analysis_daily_cap" {
  description = "Maximum analyses (model calls) per day. Protects the account from alarm storms."
  type        = number
  default     = 20
}

variable "analysis_sleep_seconds" {
  description = "Seconds to wait after the alert before collecting evidence, so CloudWatch Logs has time to arrive."
  type        = number
  default     = 45
}

locals {
  analysis_name = "agentic-devops-dev-incident-analysis"
  analysis_dir  = "${path.module}/../../../notifications/analysis"
  # 분석 폴더의 *.py 전부 + 수집기 모듈 하나를 한 zip 으로 묶는다(평평한 import).
  analysis_files = fileset(local.analysis_dir, "*.py")
  # global.anthropic.xxx → anthropic.xxx (기반 모델 ARN 에 쓰는 ID)
  analysis_foundation_model_id = replace(var.analysis_model_id, "/^[a-z]+\\./", "")
}

data "aws_caller_identity" "current" {}

data "archive_file" "analysis" {
  type        = "zip"
  output_path = "${path.module}/.build/incident-analysis.zip"

  dynamic "source" {
    for_each = local.analysis_files
    content {
      content  = file("${local.analysis_dir}/${source.value}")
      filename = source.value
    }
  }

  source {
    content  = file("${path.module}/../../../scripts/collector.py")
    filename = "collector.py"
  }
}

resource "aws_dynamodb_table" "analysis_state" {
  # 중복 이벤트 · 쿨다운 · 하루 호출 수 · 단일 실행 잠금. TTL(expires_at)로 저절로 지워진다.
  name         = "${local.analysis_name}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "${local.analysis_name}-state"
  }
}

resource "aws_cloudwatch_log_group" "analysis" {
  # Terraform 이 만들어야 destroy 때 같이 지워진다(Lambda 가 자동으로 만든 로그 그룹은 destroy 뒤에도 남는다).
  name              = "/aws/lambda/${local.analysis_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "analysis" {
  name = "${local.analysis_name}${var.iam_name_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "analysis" {
  name = "${local.analysis_name}-policy"
  role = aws_iam_role.analysis.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "OwnLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.analysis.arn}:*"]
      },
      {
        Sid      = "State"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
        Resource = [aws_dynamodb_table.analysis_state.arn]
      },
      {
        Sid      = "TelegramToken"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.telegram_bot_token.arn]
      },
      {
        Sid    = "ModelInvokeOnly"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.analysis_model_id}",
          "arn:aws:bedrock:*::foundation-model/${local.analysis_foundation_model_id}",
        ]
      },
      # --- 증거 수집: 읽기 전용만. 알람·로그·ECS 서비스는 이 스택의 것으로 범위를 좁혔다. ---
      {
        Sid      = "ReadAlarm"
        Effect   = "Allow"
        Action   = ["cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmHistory"]
        Resource = [aws_cloudwatch_metric_alarm.high_5xx.arn]
      },
      {
        Sid      = "ReadMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:GetMetricStatistics"]
        Resource = ["*"] # 지표 조회는 리소스 단위 제한을 지원하지 않는다
      },
      {
        Sid      = "ReadAppLogs"
        Effect   = "Allow"
        Action   = ["logs:FilterLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.app.arn}:*"]
      },
      {
        Sid      = "ReadEcsService"
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices"]
        Resource = [aws_ecs_service.app.id]
      },
      {
        Sid      = "ReadTaskDefAndTargets"
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition", "elasticloadbalancing:DescribeTargetHealth"]
        Resource = ["*"] # 이 두 조회도 리소스 단위 제한을 지원하지 않는다
      },
    ]
  })
}

resource "aws_lambda_function" "analysis" {
  function_name = local.analysis_name
  role          = aws_iam_role.analysis.arn
  handler       = "analysis_handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 120
  memory_size   = 256

  # 꺼짐 = 예약 동시성 0, 켜짐 = 제한 없음(-1). 알림 Lambda 와 같은 방식(telegram.tf).
  reserved_concurrent_executions = var.analysis_enabled ? -1 : 0

  filename         = data.archive_file.analysis.output_path
  source_code_hash = data.archive_file.analysis.output_base64sha256

  environment {
    variables = {
      ANALYSIS_ENABLED              = tostring(var.analysis_enabled)
      MODEL_ID                      = var.analysis_model_id
      TABLE                         = aws_dynamodb_table.analysis_state.name
      COOLDOWN_MINUTES              = tostring(var.analysis_cooldown_minutes)
      DAILY_CAP                     = tostring(var.analysis_daily_cap)
      SLEEP_SECONDS                 = tostring(var.analysis_sleep_seconds)
      ALARM_NAME                    = aws_cloudwatch_metric_alarm.high_5xx.alarm_name
      CLUSTER                       = aws_ecs_cluster.main.name
      SERVICE                       = aws_ecs_service.app.name
      LOG_GROUP                     = aws_cloudwatch_log_group.app.name
      TELEGRAM_BOT_TOKEN_SECRET_ARN = aws_secretsmanager_secret.telegram_bot_token.arn
      TELEGRAM_CHAT_ID              = var.telegram_chat_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.analysis, aws_iam_role_policy.analysis]

  tags = {
    Name = local.analysis_name
  }
}

resource "aws_lambda_function_event_invoke_config" "analysis" {
  # 비동기 호출이 «함수 오류»로 실패해도 자동으로 다시 부르지 않는다 — 재시도가 모델을 두 번 부르는 것을 막는다.
  # 그러나 retry 0 은 *스로틀(429)* 에는 적용되지 않는다: 킬 스위치(예약 동시성 0)로 막힌 이벤트는 대기열에 남아
  # 기본 6시간 동안 다시 시도되고, 스위치를 다시 켜면 늦게 실행되어 모델이 불린다.
  # 그래서 이벤트 수명을 60초(허용 하한)로 줄여, 스위치가 꺼져 있던 동안의 이벤트는 버려지게 한다.
  function_name                = aws_lambda_function.analysis.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 60
}

# 알림 Lambda 가 이 함수 하나만 부를 수 있게 한다(알림 Lambda 역할에 문장 하나 추가).
resource "aws_iam_role_policy" "telegram_invokes_analysis" {
  name = "agentic-devops-dev-telegram-invokes-analysis"
  role = aws_iam_role.telegram_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.analysis.arn]
    }]
  })
}
