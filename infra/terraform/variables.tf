variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Cloud Run and Artifact Registry region. europe-west1 supports direct Cloud Run domain mapping."
  type        = string
  default     = "europe-west1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "cherry-agent"
}

variable "container_image" {
  description = "Fully-qualified Artifact Registry container image."
  type        = string
}

variable "gemini_model" {
  description = "Gemini model ID used by Google ADK and document extraction."
  type        = string
  default     = "gemini-3.7-flash"
}

variable "domain" {
  description = "Verified custom domain for the Cloud Run service."
  type        = string
  default     = "finops.cherrymoney.co.uk"
}

variable "enable_domain_mapping" {
  description = "Create the Cloud Run preview domain mapping after domain ownership is verified."
  type        = bool
  default     = false
}

variable "create_firestore_database" {
  description = "Create the project's default Firestore Native database. Set false when one already exists."
  type        = bool
  default     = false
}

variable "public_access" {
  description = "Permit unauthenticated access to the hackathon demo."
  type        = bool
  default     = true
}
