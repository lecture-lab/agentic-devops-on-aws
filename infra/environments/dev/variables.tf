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

variable "vpc_cidr" {
  description = "CIDR block for the training VPC."
  type        = string
  default     = "10.20.0.0/16"
}

# --- Entry layer / compute (alb.tf, ecs.tf) ---

variable "container_port" {
  description = "Port the sample container listens on and the ALB target group forwards to."
  type        = number
  default     = 80
}

variable "container_image" {
  description = "Public container image for the pipeline smoke test (not the course application)."
  type        = string
  default     = "public.ecr.aws/nginx/nginx:latest"
}

variable "desired_count" {
  description = "Desired ECS Fargate task count for the app service."
  type        = number
  default     = 2
}

variable "task_cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU, the smallest Fargate size)."
  type        = string
  default     = "256"
}

variable "task_memory" {
  description = "Fargate task memory in MiB (512, paired with 256 CPU units)."
  type        = string
  default     = "512"
}

# --- Database (rds.tf) ---

variable "db_instance_class" {
  description = "RDS instance class. Smallest class that fits AWS free-tier eligibility."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "PostgreSQL engine version. Confirmed orderable for db.t4g.micro/db.t3.micro in ap-northeast-2 at plan time."
  type        = string
  default     = "16.15"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GiB (minimal, within the free-tier allowance)."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Initial database name created on the RDS instance."
  type        = string
  default     = "appdb"
}

variable "db_username" {
  description = "RDS master username."
  type        = string
  default     = "app_admin"
}
