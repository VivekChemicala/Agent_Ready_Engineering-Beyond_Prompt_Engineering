Review of your change found problems. Please fix them, keep pytest and flake8 green, push to the same branch, and reply with the new commit SHA.

- A line whose offset is not a non-negative integer is MALFORMED_EVENT, and source_offset must then be null.
- A missing, null, empty or whitespace-only customer_id is NULL_CUSTOMER_ID.
- One reason per event, first failing check wins: MALFORMED_EVENT > NULL_CUSTOMER_ID > SCHEMA_VIOLATION > INVALID_CURRENCY > DUPLICATE_TRANSACTION.
