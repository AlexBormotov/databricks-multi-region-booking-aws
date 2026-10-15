# Keyed by region: each region's functions connect to their local cluster.
output "endpoints" {
  value = {
    (data.aws_region.this.region) = "${aws_dsql_cluster.primary.identifier}.dsql.${data.aws_region.this.region}.on.aws"
    (local.peer_region)           = "${aws_dsql_cluster.peer.identifier}.dsql.${local.peer_region}.on.aws"
  }
}

output "cluster_arns" {
  value = {
    (data.aws_region.this.region) = aws_dsql_cluster.primary.arn
    (local.peer_region)           = aws_dsql_cluster.peer.arn
  }
}
