variable "application_name" {
  description = "Application name"
  type        = string
}

variable "charm_channel" {
  description = "Charm channel"
  type        = string
  default     = "latest/stable"
}

variable "model_name" {
  description = "Model name"
  type        = string
}

variable "num_units" {
  description = "Number of units"
  type        = number
  default     = 1
}

variable "trust" {
  description = "Equiv of juju deploy --trust"
  type = bool
  default = false
}

variable "config" {
  description = "Config options as in the ones we pass in juju config"
  type = map(string)
  default = {}
}
