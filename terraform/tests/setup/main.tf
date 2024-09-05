terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "3.5.1"
    }
  }
}

resource "random_pet" "app_name_suffix" {
  length = 1
}

output "app_name_suffix" {
  value = random_pet.app_name_suffix.id
}