# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in webhook-inspector, please report it privately. **Do not open a public GitHub issue.**

### Preferred channel

Open a [private security advisory](https://github.com/hooktrace-io/hooktrace/security/advisories/new) directly on GitHub. This keeps the report confidential and lets us collaborate on a fix before public disclosure.

### What to include

- A clear description of the vulnerability
- Steps to reproduce
- Affected version or commit SHA
- Impact assessment (data exposure, RCE, DoS, etc.)
- Suggested mitigation if you have one

### Response timeline

This is a side-project maintained by a single person. Best-effort response within 7 days. Critical issues (RCE, data leak) will be prioritized.

### Out of scope

- Reports against the public live instance at `app.hooktrace.io` involving denial of service (the instance runs on minimal compute by design)
- Issues already addressed by the launch hardening (rate limiting + Cloudflare WAF in place since V3 public launch)
- Best-practice recommendations without an exploitable scenario

### Supported versions

Only the latest commit on `main` is supported. There are no backported security fixes.
