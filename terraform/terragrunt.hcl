remote_state {
  backend = "s3"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }
  config = {
    bucket  = "anorum-homelab"
    key     = "terraform/${path_relative_to_include()}/terraform.tfstate"
    region  = "us-west-2"
    encrypt        = true
    use_lockfile   = false
  }
}
