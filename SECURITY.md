# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in webhook-inspector, please report it privately. **Do not open a public GitHub issue.**

### Preferred channel

Open a [private security advisory](https://github.com/quaxsze/webhook-inspector/security/advisories/new) directly on GitHub. This keeps the report confidential and lets us collaborate on a fix before public disclosure.

### What to include

- A clear description of the vulnerability
- Steps to reproduce
- Affected version or commit SHA
- Impact assessment (data exposure, RCE, DoS, etc.)
- Suggested mitigation if you have one

### Response timeline

This is a side-project maintained by a single person. Best-effort response within 7 days. Critical issues (RCE, data leak) will be prioritized.

### Out of scope

- Reports against the public live instance at `app.odessa-inspect.org` involving denial of service (the instance runs on minimal compute by design)
- Issues already documented in the [roadmap](README.md#roadmap) as known gaps (rate limiting, WAF — planned for V4)
- Best-practice recommendations without an exploitable scenario

### Supported versions

Only the latest commit on `main` is supported. There are no backported security fixes.
