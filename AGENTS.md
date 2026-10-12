# Agent Instructions

## Project

This repository is used for the Agentic DevOps on AWS training course.

## Default Environment

Development only.

## Safety

- Never run terraform apply without explicit approval.
- Never run terraform destroy without explicit approval.
- Never modify production resources.
- Do not commit secrets.
- Prefer read-only inspection before modification.
- Explain assumptions before making infrastructure changes.

## Validation

For Terraform changes:

1. run terraform fmt
2. run terraform validate
3. generate terraform plan when possible
4. summarize changed resources
5. report risks and assumptions

## AWS

Default region:

us-east-1

## Tags

All supported resources must use:

- Project
- Environment
- ManagedBy
