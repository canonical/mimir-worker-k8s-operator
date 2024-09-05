# Terraform executes `run` blocks sequentially.
# Every `run` block runs a terraform apply command.

# TODO: figure out why this test fails
#  run "deploy_minimal_context"... fail
#╷
#│ Error: Reference to undeclared resource
#│
#│   on tests/integrated.tftest.hcl line 36, in run "deploy_minimal_context":
#│   36:     condition     = juju_application.mimir_worker.name == "worker-${run.setup_tests.app_name_suffix}"
#│
#│ A managed resource "juju_application" "mimir_worker" has not been declared in the root module.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "deploy_app" {
  variables {
    app_name   = "worker-${run.setup_tests.app_name_suffix}"
    model_name = "mimir5"
    channel    = "latest/edge"
    units      = 3
    trust      = true
    config = {
      role-all = "true"
    }
  }
}

run "deploy_minimal_context" {
  module {
    source = "./tests/minimal"
  }

  variables {
    app_name = "worker-${run.setup_tests.app_name_suffix}"
    model_name = "mimir5"
  }

  # TODO change assertions to something more sensible
  # TODO figure out how to use the http module without an app IP as an output
  assert {
    condition     = juju_application.mimir_worker.name == "worker-${run.setup_tests.app_name_suffix}"
    error_message = "App name mismatch"
  }
}