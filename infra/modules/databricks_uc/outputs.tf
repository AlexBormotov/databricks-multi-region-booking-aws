output "landing_path" {
  value = databricks_external_location.landing.url
}

output "warehouse_id" {
  value = databricks_sql_endpoint.demo.id
}
