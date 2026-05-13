variable "project_id" {
  type        = string
  description = "GCP project ID (e.g. webhook-inspector-stan-dev)"
}

variable "region" {
  type        = string
  default     = "europe-west1"
  description = "Default region for all regional resources."
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Deployment environment label (dev/staging/prod)."
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Tag of the webhook-inspector image in Artifact Registry."
}

variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Cloud SQL instance tier."
}

variable "endpoint_ttl_days" {
  type        = number
  default     = 7
  description = "Webhook endpoint TTL in days."
}

variable "ingestor_min_instances" {
  type    = number
  default = 0
}

variable "ingestor_max_instances" {
  type    = number
  default = 20
}

variable "app_min_instances" {
  type    = number
  default = 1
}

variable "app_max_instances" {
  type    = number
  default = 5
}

variable "github_repo" {
  type        = string
  default     = "quaxsze/webhook-inspector"
  description = "GitHub repo allowed to deploy via Workload Identity Federation (format: owner/repo)."
}

variable "domain" {
  type        = string
  default     = ""
  description = "Apex domain (e.g. 'example.com'). Cloud Run is mapped to app.<domain> and hook.<domain>. Empty string disables domain mapping (used in CI deploys that don't touch DNS)."
}

variable "cloudflare_api_token" {
  type        = string
  default     = ""
  description = "Cloudflare API token with Zone DNS edit rights. Provided via TF_VAR_cloudflare_api_token. Empty for CI runs that don't touch Cloudflare resources."
  sensitive   = true
}

variable "cloudflare_zone_id" {
  type        = string
  default     = ""
  description = "Cloudflare Zone ID of the domain (from the dashboard Overview page). Empty for CI runs."
}

variable "owner_email" {
  type        = string
  description = "Email address that receives alert notifications."
}
