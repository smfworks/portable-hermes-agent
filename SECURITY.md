# Security Policy for SMF Forge Desktop

> **Project:** `smfworks/smf-windows-hermes`
> **Maintainer:** SMF Works Security Team (security@smfworks.com)
> **Effective Date:** 2026-04-29
> **Last Updated:** 2026-04-30

---

## Supported Versions

The following versions of SMF Forge Desktop receive security patches.

| Version | Status | Notes |
|---------|--------|-------|
| `0.1.x` (current) | **Supported** | Actively maintained; patches applied to `main` |
| Upstream (`NousResearch/hermes-agent`) | **Not tracked** | We forked upstream; our security fixes are not automatically backported there |

**Unsupported:** Any version prior to `0.1.0` or any build from the original `aivrar/portable-hermes-agent` fork before SMF Works branding (commit `5aa386d5`) receives no security commitments.

---

## Security Baseline

We operate under a **"never trust user input"** model for all agent-facing tools. All network requests, file operations, and command invocations are treated as potentially malicious.

### Current Posture (as of commit `5ddc73fa`)

| Category | Risk | Mitigation Status |
|----------|------|-------------------|
| **RCE via `eval()` in workflow_tool** | Critical | Fixed in `9cbf59f2` — replaced with AST-based safe evaluator |
| **SSRF / private-IP navigation** | **High** | Fixed in `5ddc73fa` — `tools/url_safety.py` with IP blocklist + DNS rebinding protection; integrated into `browser_navigate()` |
| **Sudo password cache leakage** | **High** | Fixed in `5ddc73fa` — thread-local `sudo_password` replaces global variable; passwords no longer leak across concurrent sessions |
| **Credential leakage in logs (`OLLAMA_API_KEY`)** | **High** | Fixed in `5ddc73fa` — `agent/redact.py` now covers OLLAMA, generic `*_API_KEY`, and all credential-bearing env names |
| **MCP OAuth CSRF / session fixation** | **Medium** | Fixed in `5ddc73fa` — PKCE state parameter generation with `secrets.token_urlsafe(32)` and timing-safe `secrets.compare_digest` verification |
| **TUI blind keystroke approval** | **Medium** | Fixed in `5ddc73fa` — approval prompt defaults to `"deny"` instead of `"once"`; accidental Enter no longer approves dangerous commands |

### Architecture Protections

| Protection | Implementation |
|-----------|----------------|
| **IP blocklist** | RFC 1918, loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`, `fe80::/10`), CGNAT (`100.64.0.0/10`), benchmark (`198.18.0.0/15`), test nets |
| **Cloud metadata guard** | AWS IMDS (`169.254.169.254`), GCP `metadata.google.internal`, Azure IMDS, Alibaba (`100.100.100.200`), Oracle, DigitalOcean, Hetzner |
| **DNS rebinding guard** | `is_safe_url()` resolves hostname before validation; rejects if any A/AAAA record is private |
| **URL scheme allowlist** | Only `http` and `https` permitted; `ftp`, `file`, `gopher`, `javascript`, `data`, etc. rejected |
| **Host pattern denylist** | `localhost`, `*.internal`, `metadata.*`, `instance-data.*`, `0.0.0.0` |
| **Bidi attack stripping** | URL input stripped of bidirectional formatting characters (`\u200e`, `\u200f`, `\u202a-\u202e`, `\u2066-\u2069`) |
| **Dangerous command detection** | Regex-based pattern matching for `rm -rf`, `chmod 777`, `mkfs`, `dd`, SQL `DROP`, shell via `-c`, pipe-to-shell, fork bomb, `tee` to system paths |
| **Approval state machine** | Per-session / permanent allowlist with thread-safe locking; defaults to `"deny"` |
| **Secret redaction** | Regex-based masking for API keys, PATs, OAuth tokens, connection strings, Telegram bot tokens, private keys, phone numbers |

---

## Reporting a Vulnerability

**DO NOT** open a public GitHub issue for security vulnerabilities. We follow a **90-day disclosure window** with coordinated disclosure.

### Preferred Channel

Send encrypted email to: **security@smfworks.com**

We support PGP. Public key available upon request or in the repository's `.well-known/security.txt` (if hosted).

### What to Include

1. **Description** — what the vulnerability is and how it manifests
2. **Impact** — what an attacker can achieve (data exfiltration, RCE, DoS, etc.)
3. **Reproduction steps** — minimal commands or code that demonstrates the issue
4. **Affected version(s)** — `git rev-parse HEAD` or package version
5. **Suggested fix** — if you have one; we welcome patches
6. **Your disclosure preference** — coordinated (default), full disclosure, or embargo

### Our Commitments

- **Acknowledgment:** We reply within 72 hours confirming receipt.
- **Triage:** We assign a severity (Critical / High / Medium / Low) within 7 days.
- **Patch:** We aim to ship a fix within 14 days for Critical/High; 30 days for Medium; 90 days for Low.
- **Credit:** We publicly credit reporters who desire attribution in our advisory and release notes.
- **No legal action:** We will not pursue legal action against researchers who act in good faith and follow responsible disclosure.

### Bug Bounty

SMF Works does not currently run a paid bug bounty program. Priority treatment and public acknowledgment are our standard reward.

---

## Known Vulnerabilities Not Yet Addressed

These are tracked; fixes are in backlog.

| ID | File | Vulnerability | Severity | Status |
|----|------|---------------|----------|--------|
| SEC-001 | `tools/browser_tool.py` | CDP endpoint `_resolve_cdp_override()` resolves arbitrary HTTP(S) without URL validation — open to SSRF if `BROWSER_CDP_URL` is attacker-controlled | **Medium** | **Backlog** |
| SEC-002 | `tools/browser_tool.py` | Cloud provider registry (`_PROVIDER_REGISTRY`) loads providers dynamically with no signature verification — malicious provider could be injected | **Medium** | **Backlog** |
| SEC-003 | `tools/terminal_tool.py` | Modal / Daytona / Singularity execution environments spawn remote containers; no container escape hardening or network isolation beyond platform defaults | **Medium** | **Won't fix** — platform-level responsibility |
| SEC-004 | `tools/approval.py` | Smart approval via auxiliary LLM (`_smart_approve_command`) is not deterministic; model hallucinations could approve dangerous commands unpredictably | **Low** | **Backlog** — requires model-level fix |
| SEC-005 | `gateway/` | Upstream gateway platform integrations (Discord, Telegram, Slack, Matrix) parse untrusted message content without rigorous input sanitization before passing to LLM | **Medium** | **Backlog** |

---

## Security Test Suite

Run the security regression tests:

```bash
cd /path/to/smf-windows-hermes
python -m unittest tests.p1_security_fixes -v
```

These tests verify:
- SSRF IP blocking (public vs. private)
- Thread-local sudo password isolation
- Redaction coverage (OLLAMA, generic API keys)
- MCP OAuth CSRF state generation and verification
- TUI approval default-to-deny behavior

---

## Third-Party Security Scanning

We recommend the following tools for continuous security assessment of this codebase:

| Tool | Command | What it catches |
|------|---------|-----------------|
| **bandit** | `bandit -r tools/ agent/ cli.py run_agent.py` | Python-specific security anti-patterns (SQLi, hardcoded creds, unsafe eval, subprocess, etc.) |
| **semgrep** | `semgrep --config=auto .` | Cross-language security patterns; detects SSRF, path traversal, deserialization |
| **pip-audit** | `pip-audit` | Known vulnerabilities in installed dependencies (CVE database) |
| **safety check** | `safety check` | Alternative dependency vulnerability scanner |

These are enabled in the dev environment via `pip install bandit semgrep pip-audit`.

---

## Contact

- **General:** security@smfworks.com
- **Keybase:** liamhermes (if available)
- **Response SLA:** 72h acknowledgment, 7-day triage, 14-day critical patch target

---

> *This policy is adapted from the [Google Security Policy](https://github.com/google/oss-vulnerability-guide) and [GitHub Security Advisories](https://docs.github.com/en/code-security/security-advisories) best practices. Licensed under MIT.*
