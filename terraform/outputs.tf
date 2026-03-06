output "app_name" {
  value = juju_application.mimir_worker.name
}

output "provides" {
  value = {
  }
}

output "requires" {
  value = {
    mimir_cluster = "mimir-cluster"
  }
}
