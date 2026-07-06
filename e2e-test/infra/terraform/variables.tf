variable "aws_region" {
  description = "AWS region for E2E test infrastructure"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the E2E VPC"
  type        = string
  default     = "10.100.0.0/24"
}

variable "instance_type" {
  description = "EC2 instance type for test nodes"
  type        = string
  default     = "t3.medium"
}

variable "spot_max_price" {
  description = "Maximum spot price (empty string = on-demand price cap)"
  type        = string
  default     = ""
}

variable "ami_id" {
  description = "AMI ID (Ubuntu 24.04). Leave empty to use latest."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key for inter-node access"
  type        = string
}

variable "github_run_id" {
  description = "GitHub Actions run ID for resource tagging"
  type        = string
  default     = "local"
}

variable "matrix_shared_secret" {
  description = "Synapse registration shared secret"
  type        = string
  sensitive   = true
}

variable "mycelium_db_password" {
  description = "Password for mycelium-db PostgreSQL"
  type        = string
  sensitive   = true
  default     = "e2e-test-password"
}

variable "bedrock_access_key_id" {
  description = "AWS access key for Bedrock LLM calls"
  type        = string
  sensitive   = true
}

variable "bedrock_secret_access_key" {
  description = "AWS secret key for Bedrock LLM calls"
  type        = string
  sensitive   = true
}
