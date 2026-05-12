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
