terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  ami_id = var.ami_id != "" ? var.ami_id : data.aws_ami.ubuntu.id
  nodes = {
    orchestrator = { index = 0, role = "orchestrator" }
    node2        = { index = 1, role = "agent" }
    node3        = { index = 2, role = "agent" }
  }
  common_tags = {
    Project   = "mycelium-e2e"
    ManagedBy = "terraform"
    RunID     = var.github_run_id
  }
}

# --- Networking ---

resource "aws_vpc" "e2e" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "mycelium-e2e-vpc" })
}

resource "aws_internet_gateway" "e2e" {
  vpc_id = aws_vpc.e2e.id
  tags   = merge(local.common_tags, { Name = "mycelium-e2e-igw" })
}

resource "aws_subnet" "e2e" {
  vpc_id                  = aws_vpc.e2e.id
  cidr_block              = var.vpc_cidr
  map_public_ip_on_launch = true
  tags                    = merge(local.common_tags, { Name = "mycelium-e2e-subnet" })
}

resource "aws_route_table" "e2e" {
  vpc_id = aws_vpc.e2e.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.e2e.id
  }

  tags = local.common_tags
}

resource "aws_route_table_association" "e2e" {
  subnet_id      = aws_subnet.e2e.id
  route_table_id = aws_route_table.e2e.id
}

resource "aws_security_group" "e2e" {
  name_prefix = "mycelium-e2e-"
  vpc_id      = aws_vpc.e2e.id
  description = "Allow all traffic within E2E cluster + SSH from GH runner"

  # All traffic within the security group
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  # SSH from anywhere (GH runner IP not known ahead of time)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "SSH access for GitHub Actions runner"
  }

  # All outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

# --- SSH Key ---

resource "aws_key_pair" "e2e" {
  key_name_prefix = "mycelium-e2e-"
  public_key      = var.ssh_public_key
  tags            = local.common_tags
}

# --- EC2 Spot Instances ---

resource "aws_instance" "node" {
  for_each = local.nodes

  ami                    = local.ami_id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.e2e.id
  vpc_security_group_ids = [aws_security_group.e2e.id]
  key_name               = aws_key_pair.e2e.key_name

  instance_market_options {
    market_type = "spot"
    spot_options {
      max_price          = var.spot_max_price != "" ? var.spot_max_price : null
      spot_instance_type = "one-time"
    }
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/userdata.sh.tpl", {
    node_role                 = each.value.role
    node_index                = each.value.index
    ssh_public_key            = var.ssh_public_key
    matrix_shared_secret      = var.matrix_shared_secret
    mycelium_db_password      = var.mycelium_db_password
    bedrock_access_key_id     = var.bedrock_access_key_id
    bedrock_secret_access_key = var.bedrock_secret_access_key
    orchestrator_ip           = ""  # Filled post-apply via provisioner
  })

  tags = merge(local.common_tags, {
    Name = "mycelium-e2e-${each.key}"
    Role = each.value.role
  })
}
