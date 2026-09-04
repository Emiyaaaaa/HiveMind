variable "kubeconfig_path" {
  type        = string
  description = "Path to a kubeconfig that can install the AgentFlow chart."
  default     = "~/.kube/config"
}

variable "kubeconfig_context" {
  type        = string
  description = "Optional kubeconfig context. Empty uses the current context."
  default     = null
}

variable "namespace" {
  type        = string
  description = "Kubernetes namespace for AgentFlow."
  default     = "agentflow"
}

variable "create_namespace" {
  type    = bool
  default = true
}

variable "release_name" {
  type    = string
  default = "agentflow"
}

variable "install_keda" {
  type        = bool
  description = "Install KEDA so workers can scale on Prometheus queue delay."
  default     = true
}

variable "keda_namespace" {
  type    = string
  default = "keda"
}

variable "api_image_repository" {
  type    = string
  default = "agentflow-api"
}

variable "api_image_tag" {
  type    = string
  default = "0.1.0"
}

variable "worker_image_repository" {
  type    = string
  default = "agentflow-worker"
}

variable "worker_image_tag" {
  type    = string
  default = "0.1.0"
}

variable "postgres_enabled" {
  type        = bool
  description = "Deploy the chart's demo Postgres StatefulSet. Prefer a managed database in production."
  default     = false
}

variable "redis_enabled" {
  type        = bool
  description = "Deploy the chart's demo Redis. Prefer a managed Redis in production."
  default     = false
}

variable "database_jdbc_url" {
  type    = string
  default = "jdbc:postgresql://postgres:5432/agentflow"
}

variable "database_sqlalchemy_url" {
  type      = string
  default   = "postgresql+asyncpg://agentflow:agentflow@postgres:5432/agentflow"
  sensitive = true
}

variable "database_username" {
  type    = string
  default = "agentflow"
}

variable "database_password" {
  type      = string
  default   = ""
  sensitive = true
}

variable "redis_host" {
  type    = string
  default = "redis"
}

variable "redis_port" {
  type    = number
  default = 6379
}

variable "redis_url" {
  type      = string
  default   = "redis://redis:6379/0"
  sensitive = true
}

variable "otel_enabled" {
  type    = bool
  default = true
}

variable "otel_exporter_endpoint" {
  type    = string
  default = "http://otel-collector.observability.svc.cluster.local:4318"
}

variable "prometheus_server_address" {
  type        = string
  description = "Prometheus base URL used by the KEDA queue-delay trigger."
  default     = "http://prometheus.observability.svc.cluster.local:9090"
}

variable "worker_min_replicas" {
  type    = number
  default = 1
}

variable "worker_max_replicas" {
  type    = number
  default = 10
}

variable "target_consumer_delay_seconds" {
  type        = number
  description = "Scale out when agentflow_queue_consumer_delay meets or exceeds this many seconds."
  default     = 30
}

variable "autoscaling_enabled" {
  type    = bool
  default = true
}

variable "ingress_enabled" {
  type    = bool
  default = false
}

variable "ingress_host" {
  type    = string
  default = "agentflow.local"
}

variable "extra_helm_values" {
  type        = list(string)
  description = "Additional Helm -f values files (absolute or module-relative)."
  default     = []
}
