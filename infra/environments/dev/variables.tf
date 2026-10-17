variable "aws_region" {
  description = "AWS region used for the training environment. Korean edition: ap-northeast-2 (Seoul, the default). English edition: us-east-1 (N. Virginia) -- set aws_region in terraform.tfvars (see terraform.tfvars.example). The two Availability Zones are derived from this value (<region>a and <region>c)."
  type        = string
  default     = "ap-northeast-2"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}

variable "iam_name_suffix" {
  description = "Optional suffix for the global IAM role name. Leave empty. Set it (for example \"-b\") only when another stack in the same account already uses the default role name."
  type        = string
  default     = ""
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
  description = "Container image. Public nginx by default (minor tag pinned); the course nginx.conf is written in at start-up when inject_nginx_conf is true."
  type        = string
  default     = "public.ecr.aws/nginx/nginx:1.30"
}

variable "inject_nginx_conf" {
  description = "Write app/web/nginx.conf into the container at start-up (public nginx image + course config, no image build or ECR needed). Set false only if container_image already contains the course nginx.conf."
  type        = bool
  default     = true
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
  description = "PostgreSQL engine version. Checked orderable for db.t4g.micro/db.t3.micro (gp3) in ap-northeast-2 and in us-east-1 (read-only check on 2026-10-12/13); availability changes over time, so re-check it in the target Region before apply."
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
