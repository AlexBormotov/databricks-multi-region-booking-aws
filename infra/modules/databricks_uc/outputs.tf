# Without the trailing slash the API adds to the url: the bundle appends "/events/", and the file
# arrival trigger refuses a URL with "//".
output "landing_path" {
  value = trimsuffix(databricks_external_location.landing.url, "/")
}

output "warehouse_id" {
  value = databricks_sql_endpoint.demo.id
}
