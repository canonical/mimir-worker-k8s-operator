variable "app_name" {
  description = "Application name"
  type        = string
}

variable "model_name" {
  description = "Model name"
  type        = string
}

variable "channel" {
  description = "Charm channel"
  type        = string
  default     = "latest/stable"
}

variable "revision" {
  description = "Charm revision"
  type        = number
  nullable    = true
  default     = null
}

variable "config" {
  description = "Config options as in the ones we pass in juju config"
  type        = map(string)
  default     = {}
}

variable "units" {
  description = "Number of units"
  type        = number
  default     = 1
}

variable "trust" {
  description = "Equiv of juju deploy --trust"
  type        = bool
  default     = false
}


