resource "kubernetes_namespace_v1" "agentflow" {
  count = var.create_namespace ? 1 : 0

  metadata {
    name = var.namespace
  }
}

resource "helm_release" "keda" {
  count = var.install_keda ? 1 : 0

  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  namespace        = var.keda_namespace
  create_namespace = true
  wait             = true
  timeout          = 300
}

resource "helm_release" "agentflow" {
  name      = var.release_name
  chart     = "${path.module}/../helm/agentflow"
  namespace = var.namespace

  atomic          = true
  cleanup_on_fail = true
  wait            = true
  timeout         = 600

  values = concat(
    [
      yamlencode({
        api = {
          image = {
            repository = var.api_image_repository
            tag        = var.api_image_tag
          }
        }
        worker = {
          image = {
            repository = var.worker_image_repository
            tag        = var.worker_image_tag
          }
          autoscaling = {
            enabled                    = var.autoscaling_enabled
            provider                   = "keda"
            minReplicas                = var.worker_min_replicas
            maxReplicas                = var.worker_max_replicas
            targetConsumerDelaySeconds = var.target_consumer_delay_seconds
            prometheus = {
              serverAddress = var.prometheus_server_address
            }
          }
        }
        postgres = {
          enabled = var.postgres_enabled
        }
        redis = {
          enabled = var.redis_enabled
        }
        database = {
          jdbcUrl       = var.database_jdbc_url
          sqlalchemyUrl = var.database_sqlalchemy_url
          username      = var.database_username
          password      = var.database_password
        }
        redisExternal = {
          host = var.redis_host
          port = var.redis_port
          url  = var.redis_url
        }
        otel = {
          enabled          = var.otel_enabled
          exporterEndpoint = var.otel_exporter_endpoint
        }
        ingress = {
          enabled = var.ingress_enabled
          hosts = [
            {
              host = var.ingress_host
              paths = [
                {
                  path     = "/"
                  pathType = "Prefix"
                }
              ]
            }
          ]
        }
      })
    ],
    [for f in var.extra_helm_values : file(f)]
  )

  depends_on = [
    kubernetes_namespace_v1.agentflow,
    helm_release.keda,
  ]
}
