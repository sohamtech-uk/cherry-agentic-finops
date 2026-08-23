provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  required_services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
  ])

  runtime_roles = toset([
    "roles/aiplatform.user",
    "roles/datastore.user",
    "roles/logging.logWriter",
    "roles/pubsub.publisher",
  ])

  evidence_bucket = "${var.project_id}-cherry-finops-evidence"
}

resource "google_project_service" "required" {
  for_each = local.required_services
  project  = var.project_id
  service  = each.value

  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "cherry-agent"
  description   = "Cherry Agent container images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  account_id   = "cherry-agent-runtime"
  display_name = "Cherry Agent Cloud Run runtime"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "runtime" {
  for_each = local.runtime_roles
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "evidence" {
  name                        = local.evidence_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}


resource "google_storage_bucket_iam_member" "runtime_evidence_writer" {
  bucket = google_storage_bucket.evidence.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_pubsub_topic" "workflow_events" {
  name = "finance-workflow-events"

  message_retention_duration = "86400s"
  depends_on                 = [google_project_service.required]
}

resource "google_firestore_database" "default" {
  count = var.create_firestore_database ? 1 : 0

  project     = var.project_id
  name        = "(default)"
  location_id = "eur3"
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "app" {
  name                = var.service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email
    timeout         = "300s"

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }

      ports {
        container_port = 8080
      }

      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/healthz"
        }
      }

      env {
        name  = "CHERRY_ENVIRONMENT"
        value = "production"
      }
      env {
        name  = "CHERRY_PUBLIC_BASE_URL"
        value = "https://${var.domain}"
      }
      env {
        name  = "CHERRY_PERSISTENCE_BACKEND"
        value = "firestore"
      }
      env {
        name  = "CHERRY_GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "CHERRY_EVIDENCE_BUCKET"
        value = google_storage_bucket.evidence.name
      }
      env {
        name  = "CHERRY_PUBSUB_TOPIC"
        value = google_pubsub_topic.workflow_events.name
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.runtime,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.public_access ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_domain_mapping" "app" {
  count = var.enable_domain_mapping ? 1 : 0

  name     = var.domain
  location = var.region

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.app.name
  }
}
