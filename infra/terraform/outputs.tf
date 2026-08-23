output "cloud_run_url" {
  description = "Generated Cloud Run service URL."
  value       = google_cloud_run_v2_service.app.uri
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "evidence_bucket" {
  value = google_storage_bucket.evidence.name
}

output "pubsub_topic" {
  value = google_pubsub_topic.workflow_events.id
}

output "domain_mapping_records" {
  description = "DNS records returned by Cloud Run after domain mapping is enabled."
  value = var.enable_domain_mapping ? try(
    google_cloud_run_domain_mapping.app[0].status[0].resource_records,
    []
  ) : []
}
