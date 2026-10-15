# Aurora DSQL multi-region: active clusters in us-east-1 and us-east-2, witness in us-west-2.
# Provider 6.x takes a per-resource region, so both peers live in this one component.

locals {
  peer_region    = "us-east-2"
  witness_region = "us-west-2"
}

data "aws_region" "this" {}

resource "aws_dsql_cluster" "primary" {
  deletion_protection_enabled = false
  multi_region_properties {
    witness_region = local.witness_region
  }
}

resource "aws_dsql_cluster" "peer" {
  region                      = local.peer_region
  deletion_protection_enabled = false
  multi_region_properties {
    witness_region = local.witness_region
  }
}

resource "aws_dsql_cluster_peering" "primary" {
  identifier     = aws_dsql_cluster.primary.identifier
  clusters       = [aws_dsql_cluster.peer.arn]
  witness_region = local.witness_region
}

resource "aws_dsql_cluster_peering" "peer" {
  region         = local.peer_region
  identifier     = aws_dsql_cluster.peer.identifier
  clusters       = [aws_dsql_cluster.primary.arn]
  witness_region = local.witness_region
}
