# Note: Cloud Run domain mappings require the domain to be verified
# in GCP. The simplest path is to use Cloud Run's "*.run.app" mechanism,
# but for custom domains we need the apex zone delegated to Cloudflare,
# and then we create CNAMEs that point to Cloud Run's ghs.googlehosted.com.
#
# Domain verification: GCP does NOT require explicit verification when
# you use the `google_cloud_run_domain_mapping` resource with a verified
# domain. To verify, run once manually:
#   gcloud domains verify <domain>
# This opens a browser, you complete the verification, GCP records the
# domain as verified for your user. After that, this terraform resource
# can claim the domain for the Cloud Run services.

resource "google_cloud_run_domain_mapping" "app" {
  location = var.region
  name     = "app.${var.domain}"

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.app.name
  }
}

resource "google_cloud_run_domain_mapping" "ingestor" {
  location = var.region
  name     = "hook.${var.domain}"

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.ingestor.name
  }
}

# Cloudflare DNS records pointing to Cloud Run
resource "cloudflare_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = "app"
  content = "ghs.googlehosted.com"
  type    = "CNAME"
  proxied = false  # DNS-only: traffic goes direct to Cloud Run, Google-managed TLS
  ttl     = 300    # 5 min when not proxied

  depends_on = [google_cloud_run_domain_mapping.app]
}

resource "cloudflare_record" "hook" {
  zone_id = var.cloudflare_zone_id
  name    = "hook"
  content = "ghs.googlehosted.com"
  type    = "CNAME"
  proxied = false
  ttl     = 300

  depends_on = [google_cloud_run_domain_mapping.ingestor]
}

output "app_custom_url" {
  value = "https://app.${var.domain}"
}

output "ingestor_custom_url" {
  value = "https://hook.${var.domain}"
}
