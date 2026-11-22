# ADR-004: Typed SDK models drop unknown fields (synthetic)

Status: accepted

`platform-sdk` clients return frozen dataclasses with explicitly declared
fields. Response fields that are not declared are dropped while parsing.
Consequence: a new response field is invisible to SDK users until the SDK
model is extended, released, and the consuming repo bumps the SDK version.
