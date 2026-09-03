# Application-tier private subnets for ECS Fargate tasks.
#
# The existing "private" subnets (aws_subnet.private, main.tf) are reused
# as the database tier (see rds.tf) rather than renamed, so this change
# does not touch any already-provisioned resource. These new subnets are
# the dedicated application tier called for by ADR-001's 3-tier-per-AZ
# design (Public / Application Private / Database Private) and by
# docs/prompts/create-compute-database.md ("ECS Service ... in the
# private application subnets").
resource "aws_subnet" "app" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = {
    Name = "agentic-devops-dev-app-${count.index}"
    Tier = "application"
  }
}
