output "knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.hotels.id
}

output "knowledge_base_arn" {
  value = aws_bedrockagent_knowledge_base.hotels.arn
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.corpus.data_source_id
}

output "corpus_bucket" {
  value = aws_s3_bucket.corpus.bucket
}
