# Semantic search: a Bedrock knowledge base over the hotel corpus, stored in S3 Vectors, us-east-1.
# `make up` uploads the corpus and starts the ingestion job; `make down` destroys it all.

data "aws_caller_identity" "this" {}
data "aws_region" "this" {}

locals {
  account_id = data.aws_caller_identity.this.account_id
  region     = data.aws_region.this.region
  # Titan Text Embeddings V2 at its largest output size.
  embedding_model_arn = "arn:aws:bedrock:${local.region}::foundation-model/amazon.titan-embed-text-v2:0"
  dimensions          = 1024
}

# Destroyed with the session; its contents are synthetic and rebuilt from a seed.
resource "aws_s3_bucket" "corpus" {
  bucket        = "booking-corpus-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket                  = aws_s3_bucket.corpus.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3vectors_vector_bucket" "vectors" {
  vector_bucket_name = "booking-vectors-${local.account_id}"
  force_destroy      = true
}

resource "aws_s3vectors_index" "hotels" {
  index_name         = "hotels"
  vector_bucket_name = aws_s3vectors_vector_bucket.vectors.vector_bucket_name
  data_type          = "float32"
  dimension          = local.dimensions
  distance_metric    = "cosine"
  # Bedrock stores the chunk text and its own metadata here; filterable metadata is capped at 2 KB.
  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
}

data "aws_iam_policy_document" "kb_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${local.region}:${local.account_id}:knowledge-base/*"]
    }
  }
}

resource "aws_iam_role" "kb" {
  name                 = "booking-search-kb"
  assume_role_policy   = data.aws_iam_policy_document.kb_trust.json
  permissions_boundary = var.permissions_boundary
}

resource "aws_iam_role_policy" "kb" {
  role = aws_iam_role.kb.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = local.embedding_model_arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.corpus.arn, "${aws_s3_bucket.corpus.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3vectors:GetIndex", "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors", "s3vectors:QueryVectors"]
        Resource = aws_s3vectors_index.hotels.index_arn
      },
    ]
  })
}

resource "aws_bedrockagent_knowledge_base" "hotels" {
  name     = "booking-hotels"
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = local.dimensions
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.hotels.index_arn
    }
  }

  depends_on = [aws_iam_role_policy.kb]
}

resource "aws_bedrockagent_data_source" "corpus" {
  name                 = "hotels"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.hotels.id
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.corpus.arn
      inclusion_prefixes = ["hotels/"]
    }
  }

  # A hotel's document is short; one vector per hotel lets search read results as hotels.
  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "NONE"
    }
  }
}
