# Managed database layer: single-AZ RDS PostgreSQL, private, smallest
# free-tier-eligible instance class. Master password is generated with
# random_password (never hardcoded) and never emitted as plan/apply
# output (random_password.result and the RDS instance's derived
# password-bearing attributes are treated as sensitive by their
# providers; no output in outputs.tf references them).

resource "aws_db_subnet_group" "main" {
  name = "agentic-devops-dev-db-subnet-group"
  # Reuses the existing private subnets from main.tf as the database
  # tier -- see app-subnets.tf for why these were not renamed.
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "agentic-devops-dev-db-subnet-group"
  }
}

resource "random_password" "db_master" {
  length  = 24
  special = true
  # RDS PostgreSQL master passwords may not contain '/', '@', '"', or a
  # space; restrict the special-character set accordingly.
  override_special = "!#$%^&*()-_=+[]{}<>?"
}

resource "aws_db_instance" "main" {
  identifier     = "agentic-devops-dev-postgres"
  engine         = "postgres"
  engine_version = var.db_engine_version

  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db_master.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  # Training environment tradeoffs -- see report Assumptions/Risks:
  # backups disabled and final snapshot skipped to keep this a clean,
  # low-cost, easily torn-down lab resource. Revisit for the Production
  # Extension per ADR-001.
  backup_retention_period = 0
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true

  tags = {
    Name = "agentic-devops-dev-postgres"
  }
}
