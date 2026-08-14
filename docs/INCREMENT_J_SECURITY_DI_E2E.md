# Increment J — Deployed Security → DI End-to-End Proof

Increment J closes the deployed Security-to-DI authorization boundary after Increment I alignment.

The proof must use a runtime access token issued by the deployed Verigence Security service and verified by deployed DI against the Security JWKS. A locally minted or DI test-key JWT is not valid evidence.

Required deployed checks:

1. Security issues an access JWT containing canonical `iss=verigence-security`, `aud=verigence-platform`, Tenant scope and effective `permissions[]`.
2. DI accepts that Security-issued JWT using the configured Security JWKS.
3. `GET /v1/tenants/{tenantId}/subjects` succeeds when the token contains `di.subject.read`.
4. The same operation returns HTTP 403 when a newly issued token lacks `di.subject.read`.
5. A token for Tenant A returns HTTP 403 when used against a Tenant B URL.

The Security repository owns the deployed Increment-J workflow and temporary authorization fixture. DI remains fail-closed and does not mint an alternate test identity for this proof.
