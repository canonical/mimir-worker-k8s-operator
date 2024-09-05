resource "juju_application" "mimir_worker" {
  name  = var.app_name
  # Coordinator and worker must be in the same model
  model = var.model_name
  trust = var.trust

  charm {
    name    = "mimir-worker-k8s"
    channel = var.channel
  }
  units = var.units
  config = var.config
  # TODO: add revision, if given
}

