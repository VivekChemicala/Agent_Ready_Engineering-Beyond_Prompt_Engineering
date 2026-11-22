# Cross-repo contract change playbook (synthetic)

1. Open the change in `platform-contracts` first; release a minor version for
   additive changes.
2. Release `platform-sdk` pinning the new contracts version if any SDK model or
   publish validation is affected; bump the SDK in every consuming repo that
   needs the new fields.
3. Make consumers ready before producers emit (strict consumers first, see the
   consumer registry), then ship producers.
4. Each consumer keeps contract tests for what it reads; add/extend a
   `platform-e2e` suite for any new cross-service behaviour and run it in `int`.
5. Gate user-visible behaviour behind a feature flag; roll out per environment.
