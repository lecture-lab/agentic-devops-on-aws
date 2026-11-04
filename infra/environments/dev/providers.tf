terraform {
  required_version = ">= 1.15.0"

  # 값은 코드에 적지 않는다 — 워크플로가 terraform init -backend-config 로 넘긴다(L08-02 와 같은 모양).
  backend "s3" {}

  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    random = {
      source = "hashicorp/random"
    }
    archive = {
      source = "hashicorp/archive"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "agentic-devops"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
