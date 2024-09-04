resource "juju_application" "mimir_worker" {
  name  = var.application_name
  # Coordinator and worker must be in the same model
  model = var.model_name
  trust = var.trust

  charm {
    name    = "mimir-worker-k8s"
    channel = var.charm_channel
  }
  units = var.num_units
  config = var.config
}

