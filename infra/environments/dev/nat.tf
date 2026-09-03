# Outbound reachability for the application-tier private subnets.
#
# Without this, aws_subnet.app (app-subnets.tf) has no route beyond the
# VPC's default local-only main route table, and ECS Fargate tasks
# placed there cannot pull their container image from ECR or ship logs
# to CloudWatch Logs (AWS requires internet or VPC-endpoint reachability
# for both, even for images in ECR Public). A single NAT Gateway is the
# simplest fix and matches ADR-001's "가장 이해하기 쉬운 방식" framing for
# egress; the accepted alternative (VPC Interface/Gateway Endpoints for
# ecr.api/ecr.dkr/logs/S3) would avoid the NAT Gateway's recurring cost
# but adds more resources and still doesn't grant general internet
# egress -- not used here, kept as a documented alternative.
#
# Recurring cost: this is the one genuinely expensive addition in this
# stack -- see the cost/cleanup note in alb.tf.

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "agentic-devops-dev-nat-eip"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  # Placed in an existing public subnet -- a NAT Gateway must sit in a
  # subnet that already routes to the internet gateway.
  subnet_id = aws_subnet.public[0].id

  tags = {
    Name = "agentic-devops-dev-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "app" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "agentic-devops-dev-app-rt"
  }
}

resource "aws_route_table_association" "app" {
  count          = 2
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app.id
}
