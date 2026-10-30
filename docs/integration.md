# Contract for volunteer.pickyour.ai

The website is not built or hosted by this repository. No DNS or Pages setup is needed. Consume the public, generated, versioned directory at:

```text
https://raw.githubusercontent.com/Pick-Your-AI/pick-your-ai-volunteers/main/public/directory.v1.json
```

Resolve stable IDs across teams, repositories, Projects, roles and opportunities. Filter many-to-many relationships instead of assuming a hierarchy. Display verification time, unknown fields, recruitment status, capacity and priority rationale. Run the deterministic recommendation function server-side or port its documented ordering with parity tests; always expose browse-all. Cache by commit SHA/ETag and show staleness rather than presenting old availability as current.

Initial submission is an ordinary GitHub link:

```text
https://github.com/Pick-Your-AI/pick-your-ai-volunteers/issues/new?template=application.yml
```

GitHub renders the generated options and requires a signed-in user. Public status is the linked issue and its bot audit comments; the website can link there now. A public REST read (`GET /repos/Pick-Your-AI/pick-your-ai-volunteers/issues/{number}` and paginated `/comments`) needs no private credential but has unauthenticated rate limits. Do not display untrusted Markdown as raw HTML. The current bot marker is `<!-- volunteer-ledger:v1 -->`; only comments created by github-actions[bot] through the github-actions App are authoritative. An arbitrary comment with that marker is not a status record.

Referral replies and withdrawals happen on the original GitHub application. Link users to it; applicant-identity checks happen against the signed-in GitHub event actor. There is no installed website submission endpoint, private status endpoint, webhook receiver or GitHub App for this site. Form payloads do not constitute a working API.

For a later API integration, install a dedicated GitHub App restricted to this hub with metadata:read and issues:read/write; add organization Projects:write only for the separate operator synchronizer if needed. Use server-side installation tokens, validate GitHub OAuth state/PKCE and applicant identity, and never embed tokens or app keys in browser assets. Keep secrets in the server secret store, rotate them and avoid logging request bodies. Check authorization on every write and status read, with CSRF protection, schema/length limits and allowlisted canonical IDs. Bind application ownership to authenticated GitHub ID, not supplied login strings. Use an idempotency key scoped to user and request; reconcile accepted writes before retrying, with a durable mapping to GitHub issue/comment IDs. Do not silently merge two applications: flag possible duplicates for the applicant/operator.

Verify webhook HMAC SHA-256 over raw bytes with constant-time comparison, allowlisted event types and repository IDs, and durable delivery-ID deduplication before processing. Handle edited/deleted comments and bot spoofing explicitly. Read current policy, validate allowed transition and receiver, and persist an audit/outbox transaction before GitHub side effects. Use bounded retries with jitter, GitHub rate-limit headers/Retry-After and per-user submission throttling; return 429/503 rather than dropping or duplicating requests. No public endpoint may accept an actor or approval as trusted input.

Keep public directory cache, public application content and any future restricted intake in separate stores and authorization paths. A private repository does not isolate one applicant from another. A confidential intake requires separately designed access controls, retention policy, reporting route and user disclosure before collecting sensitive data. It must not feed details into public Project fields, exports or logs.

Required website inputs: this repository and Project URL, v1 schema, release/commit pin, application link, visibility disclosure, deterministic recommendation parity tests and the eventually approved reviewer policy. Keep all live decisions on GitHub until the authenticated server implementation has its own security and end-to-end verification.
