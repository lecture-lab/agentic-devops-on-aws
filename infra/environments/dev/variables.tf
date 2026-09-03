variable "aws_region" {
  description = "AWS region used for the training environment."
  type        = string
  default     = "ap-northeast-2"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}
