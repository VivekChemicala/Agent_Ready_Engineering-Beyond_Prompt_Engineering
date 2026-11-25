# ADR-007: Decide in entitlements, enforce in consumption-gateway (synthetic)

Status: accepted

`entitlements-service` is the only place access decisions are computed.
`consumption-gateway` is the only place data is returned to consumers, so it is the
single enforcement point: rejecting requests and any row/column shaping of
results based on the decision. Warehouses are not trusted to enforce policy.
