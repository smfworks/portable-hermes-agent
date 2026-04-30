# Changelog

All notable changes to SMF Forge Desktop will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Security
- CDP endpoint SSRF hardening (`_resolve_cdp_override` URL validation)
- Cloud provider registry signature verification
- Gateway message input sanitization

## [0.1.2] — 2026-04-29

### Security — Five P1 Vulnerabilities Fixed

All fixes in commit `5ddc73fa` (PR #1).

- **SSRF protection restored** — `tools/url_safety.py` reinstated with IP blocklist (RFC 1918, loopback, link-local, CGNAT), cloud metadata guard (AWS IMDS, GCP, Azure, Alibaba, Oracle, DigitalOcean, Hetzner), DNS rebinding protection, URL scheme allowlist (`http`/`https` only), host pattern denylist, and bidi attack stripping.
- **browser_tool.py SSRF bypass closed** — `browser_navigate()` now calls `maybe_block_url()` before every navigation with graceful fail-open fallback.
- **Sudo password cache leakage eliminated** — Replaced module-level global `_cached_sudo_password` with `threading.local()`. Passwords scoped per-thread; concurrent gateway + CLI sessions no longer share credentials.
- **OLLAMA_API_KEY log leakage fixed** — `agent/redact.py` `_SECRET_ENV_NAMES` regex was truncated (ended at `A...TH`); now covers OLLAMA, generic `*_API_KEY`, `*_SECRET`, `*_TOKEN`, `*_PASSWORD`, and `ollama_*` prefixed variables.
- **MCP OAuth CSRF patched** — Added `secrets.token_urlsafe(32)` state parameter generation, thread-safe storage with `threading.Lock`, and timing-safe `secrets.compare_digest()` verification. One-time use enforced.
- **TUI blind keystroke approval fixed** — Approval prompt default selection changed from `"once"` to `"deny"`. Accidental Enter now rejects dangerous commands.

### Documentation
- Added `SECURITY.md` with supported versions, security baseline, reporting process, known vulnerabilities backlog, recommended scanning tools, and SLA commitments.
- Added `CHANGELOG.md`.

### Build
- Added PyInstaller onefile spec (`smf-forge-desktop.spec`) with auto-discovered hiddenimports, bundled data paths, UPX compression, and single-file `smf-forge-desktop.exe` output.
- Added Windows build script (`build_exe.bat`) and cross-platform dry-run script (`build_exe.sh`).
- Updated `.gitignore` with `build/`, `dist/`, `*.egg-info`.
- Updated `pyproject.toml` dev extras with `pyinstaller>=6.0` and `black>=24.0`.

## [0.1.1] — 2026-04-29

### Security
- Replaced `eval()` in `tools/workflow_tool.py:147` with AST-based safe evaluator (`ast.literal_eval` with restricted expression whitelist). Eliminates RCE vector in workflow expression resolution.

### Rebrand
- Replaced Nous Research landing page with SMF Works branding (navy `#001F3F` + amber/copper accent palette).
- Added dual Nous Research / SMF Works attribution in footer and `LICENSE`.

### Documentation
- Added comprehensive audit report (`AUDIT_REPORT_2026-04-29.md`) covering security (6/10), architecture (4/10), Windows compatibility (7/10), build (5/10), and documentation (6/10).

## [0.1.0] — 2026-04-29

### Initial Fork
- Forked from `aivrar/portable-hermes-agent` (based on `NousResearch/hermes-agent`).
- Added Windows batch wrappers: `install.bat`, `hermes.bat`, `hermes_gui.bat`, `START.bat`.
- Added portable Python 3.13 + dependency auto-installer.
- Added Tkinter GUI (`gui/` directory) with LM Studio integration.
- Ported extension modules: TTS Server (port 8200), Music Server (port 9150), ComfyUI (port 5000).
- Added workflow engine with cron scheduling.
- Added tool maker for runtime API/Python handler creation.
- Added guided mode (1,054-line built-in manual).

---

## Security Score History

| Version | Score | Notes |
|---------|-------|-------|
| 0.1.0   | 6/10  | Audit baseline — SSRF partially missing, eval() present, no security policy |
| 0.1.1   | 7/10  | eval() removed, audit published |
| 0.1.2   | 8/10  | All P1 closed, SECURITY.md added, test suite expanded, build scripts added |

---

> *For vulnerability reports: security@smfworks.com*  
> *PGP key available on request*
