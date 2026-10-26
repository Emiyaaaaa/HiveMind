output "namespace" {
  value = var.namespace
}

output "release_name" {
  value = helm_release.agentflow.name
}

output "api_service" {
  description = "Kubernetes Service for the Java API (chart fullname + '-api')."
  value       = helm_release.agentflow.name
}

output "worker_scaledobject" {
  description = "KEDA ScaledObject name when queue-delay autoscaling is enabled."
  value       = var.autoscaling_enabled ? "${helm_release.agentflow.name}-worker" : null
}
