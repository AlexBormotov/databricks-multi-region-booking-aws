---
status: accepted
---

# Semantic search is dropped

**Context.** The brief asked for a Bedrock Knowledge Base on S3 Vectors over hotel descriptions and
reviews, filtered by live availability. The code, the infrastructure and their tests were built.
On 2026-10-21 cloud run 1 stopped at the ingestion: every Bedrock model on the account answers
`Operation not allowed`, and `get-foundation-model-availability` reports `NOT_AUTHORIZED`. The
request to AWS was still open on 2026-10-24. Five sessions ran with search switched off.

**Decision.** Remove the search: the `search` Terraform unit, the `GET /search` route, the corpus
generator, the demo step, their tests and the `SEARCH` switch. The brief no longer asks for it. The
owner chose not to spend more time or money on a service the account cannot use.

**Consequences.**
- **The project shows no vector database.** The transactional store and the lakehouse are the
  whole scope.
- **Less to deploy.** `make up` applies one unit fewer, and the API role loses `bedrock:Retrieve`.
- **What reverses this.** The removed code is in git history at `1bd242a`.
