terraform {
  backend "gcs" {
    # bucket is provided via `terraform init -backend-config="bucket=..."`
    prefix = "terraform/state"
  }
}
