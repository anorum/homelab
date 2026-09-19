terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.35.1"
    }
  }
  backend "s3" {
    bucket       = "anorum-homelab"
    key          = "terraform/telemetry/roles-anywhere.tfstate"
    region       = "us-west-2"
    encrypt      = true
    use_lockfile = true
  }
}

variable "expected_account_id" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the verified homelab AWS account ID."
  }
}

variable "device_cn" {
  type = string
  validation {
    condition     = can(regex("^pi-[0-9a-f]{16}$", var.device_cn))
    error_message = "Use the enrolled Raspberry Pi board-serial certificate CN."
  }
}

provider "aws" {
  region              = "us-west-2"
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = {
      Project   = "homelab-telemetry"
      ManagedBy = "OpenTofu"
    }
  }
}

resource "aws_rolesanywhere_trust_anchor" "root" {
  name    = "homelab-telemetry-root"
  enabled = true
  source {
    source_type = "CERTIFICATE_BUNDLE"
    source_data {
      x509_certificate_data = file("${path.module}/../../../step-ca/config/root_ca.crt")
    }
  }
}

resource "aws_iam_role" "device" {
  name                 = "telemetry-${var.device_cn}"
  description          = "Certificate-authenticated Pi telemetry; upload permissions managed separately"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rolesanywhere.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"]
      Condition = {
        StringEquals = {
          "aws:SourceAccount"               = var.expected_account_id
          "aws:PrincipalTag/x509Subject/CN" = var.device_cn
          "aws:PrincipalTag/x509Issuer/CN"  = "Homelab Telemetry Intermediate CA"
        }
        ArnEquals = {
          "aws:SourceArn" = aws_rolesanywhere_trust_anchor.root.arn
        }
      }
    }]
  })
}

resource "aws_rolesanywhere_profile" "device" {
  name             = "telemetry-${var.device_cn}"
  enabled          = true
  duration_seconds = 900
  role_arns        = [aws_iam_role.device.arn]
}

output "credential_process_arns" {
  sensitive = true
  value = {
    trust_anchor = aws_rolesanywhere_trust_anchor.root.arn
    profile      = aws_rolesanywhere_profile.device.arn
    role         = aws_iam_role.device.arn
  }
}
