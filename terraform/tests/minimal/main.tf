terraform {
  required_providers {
    juju = {
      source  = "juju/juju"
      version = "0.13.0"
    }
  }
}

provider "juju" {}

variable "app_name" {
  description = "Worker application name"
  type        = string
}

variable "model_name" {
  description = "Model name"
  type        = string
}


resource "juju_application" "minio" {
  name = "minio"
  # Coordinator requires s3
  model = var.model_name
  trust = true

  charm {
    name    = "minio"
    channel = "latest/edge"
  }
  units = 1

  config = {
    access-key = "user"
    secret-key = "password"
  }
}

resource "juju_application" "s3int" {
  name = "s3int"

  model = var.model_name
  trust = true

  charm {
    name    = "s3-integrator"
    channel = "latest/edge"
  }
  units = 1

  config = {
    endpoint = "${juju_application.minio.name}-0.${juju_application.minio.name}-endpoints.${var.model_name}.svc.cluster.local:9000"
    bucket   = "mimir"
  }
}

resource "juju_application" "coord1" {
  name = "coord1"
  # Coordinator and worker must be in the same model
  model = var.model_name
  trust = true

  charm {
    name    = "mimir-coordinator-k8s"
    channel = "latest/edge"
  }
  units = 1
}

resource "null_resource" "s3fix" {

  provisioner "local-exec" {
    # There's currently no way to wait for the charm to be idle, hence the sleep
    # https://github.com/juju/terraform-provider-juju/issues/202
    command = "sleep 300;juju run -m ${var.model_name} s3int/leader sync-s3-credentials access-key=user secret-key=password;juju ssh -m ${var.model_name} minio/leader curl https://dl.min.io/client/mc/release/linux-amd64/mc --create-dirs -o '/root/minio/mc';juju ssh -m ${var.model_name} minio/leader chmod +x '/root/minio/mc';juju ssh -m ${var.model_name} minio/leader /root/minio/mc mb mimir"
  }
}

resource "juju_integration" "worker_to_coordinator" {
  model = var.model_name

  application {
    name     = juju_application.coord1.name
    endpoint = "mimir-cluster"
  }

  application {
    name     = var.app_name
    endpoint = "mimir-cluster"
  }
}

resource "juju_integration" "coordinator_to_s3int" {
  model = var.model_name

  application {
    name     = juju_application.s3int.name
    endpoint = "s3-credentials"
  }

  application {
    name     = juju_application.coord1.name
    endpoint = "s3"
  }
}