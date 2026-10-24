---
status: accepted
---

# Guest PII stays in the vault of the guest's jurisdiction

**Context.** Guests from the EU and the EEA must have their personal data stored in the EU. The
booking store is replicated between two US regions, and the events are copied to S3 and to
Databricks. Anything personal in a booking would travel with it.

**Decision.** `POST /guests` stores name, email and phone in one single-region DynamoDB table: `guests-eu`
in eu-central-1 for a declared residence in the EU or the EEA, `guests-us` in us-east-1 otherwise.
The booking store, the events, S3 and the lakehouse carry only the opaque `guest_id` and the
jurisdiction.

**Consequences.**
- **Analytics need no PII.** Every metric is computed per hotel, room and region, not per person.
- **Residence is declared, not verified.** A guest who declares the wrong country is stored by the
  declaration. This limit is documented, not solved.
- **What reverses this.** A requirement to show guest details in analytics would need a governed
  join in the guest's region, not a copy of the PII.
