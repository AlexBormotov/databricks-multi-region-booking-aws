def test_local_spark_runs_sql(spark):
    assert spark.sql("SELECT 1 + 1 AS two").first().two == 2
