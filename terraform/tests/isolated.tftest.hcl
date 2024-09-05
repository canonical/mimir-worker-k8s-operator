# Terraform executes `run` blocks sequentially.
# Every `run` block runs a terraform apply command.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "deploy_app" {
  variables {
    app_name = "worker-${run.setup_tests.app_name_suffix}"
    model_name = "mimir5"
    channel = "latest/edge"
    units = 1
    trust = true
  }

  assert {
    condition     = juju_application.mimir_worker.name == "worker-${run.setup_tests.app_name_suffix}"
    error_message = "App name mismatch"
  }
}