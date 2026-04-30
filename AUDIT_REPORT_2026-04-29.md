
# SMF Windows Hermes — Comprehensive Audit Report

**Repository:** `smfworks/smf-windows-hermes` (forked from `aivrar/portable-hermes-agent`)  
**Audit Date:** 2026-04-29  
**Auditor:** Liam Hermes, CDO SMF Works  
**Cloned To:** `/home/mikesai2/smf-works/smf-windows-hermes`

---

## 1. Executive Summary

| Dimension | Score | Verdict |
|-----------|-------|---------|
| Security | 6/10 | Several live risks; upstream cherry-picks overdue |
| Architecture | 4/10 | Severe monolith problem; 16K+ line god classes |
| Windows Compatibility | 7/10 | Has batch files + VBS + Tk GUI; path handling gaps remain |
| Build / Packaging | 5/10 | No container, no Makefile, missing dev deps |
| Documentation | 6/10 | AGENTS.md is excellent but stale; branding incomplete |
| **Overall** | **6/10** | **Viable MVP with urgent need for structural refactoring** |

---

## 2. Scale & Structure

| Metric | Value |
|--------|-------|
| Python files | **568** |
| Python source lines | **237,854** |
| Test files | **~120** |
| Top 3 largest files | `run_agent.py` (7,419 lines), `cli.py` (7,365 lines), `gateway/run.py` (5,665 lines) |

**Problem:** The three largest files contain the **entire agent loop**, **entire CLI**, and **entire messaging gateway** respectively. These are 7K+ line god classes that violate single-responsibility principle and make code review, unit testing, and parallel development extremely difficult.

---

## 3. Security Audit Findings

### 🔴 Critical — Address Immediately

| ID | Finding | Location | Severity |
|----|---------|----------|----------|
| SEC-01 | `eval()` with user-controlled JSON in `workflow_tool.py:147` | `tools/workflow_tool.py:147` | **HIGH** |
| SEC-02 | `eval()` in skills_guard test patterns (not execution, but pattern match) | `tools/skills_guard.py:290–340` | **MEDIUM** |
| SEC-03 | SSRF protection partially missing (cherry-pick blocked by deleted files) | `tools/browser_tool.py` | **HIGH** |

**SEC-01 Details:** `workflow_tool.py` line 147 uses `eval(resolved, {"__builtins__": {}}, {})` to resolve workflow step expressions. While `__builtins__` is stripped, this is still a code-injection surface. Should migrate to `ast.literal_eval` or a restricted expression evaluator.

**SEC-03 Details:** Our fork deleted `tools/url_safety.py` and its tests, making the SSRF fix from upstream (commit `7317d69f`) uncherry-pickable. The fix includes:
- Quoted `"false"` treated as `False` in browser SSRF guards
- Cloud metadata IP always-blocked list
- `auto_local_for_private_urls` hybrid routing

**Mitigation:** Either restore `url_safety.py` and its tests, or merge from upstream properly.

### 🟠 Medium

| ID | Finding | Location | Severity |
|----|---------|----------|----------|
| SEC-04 | `subprocess` with `shell=True` in CLI (hermes-cli) | `cli.py:3768` | **MEDIUM** |
| SEC-05 | `subprocess` with `shell=True` in transcription tools | `tools/transcription_tools.py:350` | **MEDIUM** |
| SEC-06 | `yaml.load()` without explicit Loader (some files) | Various | **LOW-MEDIUM** |

### 🟢 Accepted / Expected

- `tests/tools/test_yolo_mode.py:65` — test-only chmod 777 string (no real danger)
- Path traversal strings in tests (negative-test fixtures)
- Signal handling, Unix sockets, termios (acceptable for tool targeting hybrid platforms)

---

## 4. Architecture Issues

### 4.1 Monolith Classification

| File | Lines | Responsibility Violation |
|------|-------|--------------------------|
| `run_agent.py` | 7,419 | AIAgent (prompt, loop, token tracking, tool calling, reasoning, compression, guardrails) |
| `cli.py` | 7,365 | HermesCLI (input, skin engine, session mgmt, command dispatch, streaming, cron, hooks) |
| `gateway/run.py` | 5,665 | Gateway master (all platform adapters: Telegram, Discord, Slack, WhatsApp, Signal, HA) |
| `hermes_cli/main.py` | 4,190 | CLI subcommand dispatch (setup, gateway, model, tools, skills, etc.) |
| `hermes_cli/setup.py` | 3,460 | Interactive setup wizard (should be standalone module) |
| `tests/test_run_agent.py` | 3,032 | Test file also over 3K lines |

**Impact:** Tests take ~60s on average, CI pipelines are slow, onboarding new developers requires reading 7K lines to understand one class.

**Recommendation (structural):**
- `run_agent.py` → Split into: `loop/`, `context/`, `tool_orchestrator.py`, `reasoning.py`, `compression.py`
- `cli.py` → Split into: `cli/session.py`, `cli/skin.py`, `cli/commands/`, `cli/display.py`
- `gateway/run.py` → Split into: `gateway/platforms/` per adapter file (already exists, but `run.py` still centralizes dispatch)

### 4.2 Deep Nesting

The deepest nesting found was **15 levels** in `tests/tools/test_tirith_security.py:575`.
Production code reached **14 levels** in `gui/lm_studio.py:186`.

Recommendation: Refactor nested `if` chains into guard clauses or early returns.

### 4.3 Duplicate Code

**1,604** exact 5-line duplicate blocks were found across Python files. Highest duplication occurs in:
- `gateway/platforms/*.py` — shared response formatting
- `tools/` — repeated error handling patterns
- CLI/gateway command dispatch — near-identical routing logic

---

## 5. Windows-Specific Gaps

### 5.1 What's Present (Good)

| Asset | Status |
|-------|--------|
| `hermes_gui.bat` | ✅ Tkinter launcher |
| `install.bat` | ✅ Windows pip install wrapper |
| `START.bat` | ✅ Convenience entry point |
| `hermes_gui.vbs` | ✅ VBS launcher (hides terminal) |
| `scripts/install.cmd` / `.ps1` | ✅ Installer scripts |
| `gui/` directory | ✅ Full Tkinter app with extensions, permissions, LM Studio |

### 5.2 What's Missing (Gaps)

| Gap | Severity | Notes |
|-----|----------|-------|
| WiX / Inno Setup installer | HIGH | No `.msi` or `.exe` installer; Windows users need Python installed |
| Single-file executable (PyInstaller) | HIGH | No standalone `.exe` — defeats portability promise |
| Windows registry integration | MEDIUM | No file association, no shell context menu |
| .NET / WinUI3 rewrite path | MEDIUM | Tkinter shows its age on HiDPI displays |
| Path separator handling | MEDIUM | 231 potential hardcoded Unix paths found (`/tmp/`, `/var/`, `.startswith("/")`) |
| No Windows service mode | LOW | Not needed for desktop |
| No Windows Terminal profile | LOW | Nice-to-have |

**Path Issue Detail:** Many slash-based path checks like `target.startswith("/")` are used for slash-command detection, but some are actual filesystem assumptions. Lines to audit:
- `hermes_cli/gateway.py:529` — `/var/lib/systemd/linger/` (Linux-only)
- Various `if text.startswith("/")` — these are actually **command prefix checks**, not file paths. These are **safe**.
- Any `os.path.join("/tmp", ...)` or `/dev/null` references need cross-platform guards.

---

## 6. Dependency & Build Analysis

### 6.1 Dependency Hygiene

| Check | Status |
|-------|--------|
| requirements.txt version pins | **6/23 pinned** — 16 are floating |
| pyproject.toml metadata | ✅ Present |
| Dev dependencies (pytest, mypy, black, bandit, ruff) | **❌ None present** |
| Containerization (Dockerfile) | ❌ Missing |
| tox config | ❌ Missing |
| Makefile | ❌ Missing |
| .gitignore completeness | ⚠️ Missing `build/`, `dist/`, `*.egg-info`, `.DS_Store` |

### 6.2 Import Performance

Four files import heavy ML/audio modules at module level:
- `tools/neutts_synth.py` → `numpy` (justifiable)
- `tools/tts_tool.py` → `numpy` (justifiable)
- `tools/voice_mode.py` → `numpy` (justifiable)
- `skills/mlops/training/.../basic_grpo_training.py` → `torch` (opt-in skill, acceptable)

No critical startup-time regressions detected.

---

## 7. Branding & Documentation

### 7.1 Stale References

| Stale Term | Count | Primary Locations |
|------------|-------|-------------------|
| `portable-hermes-agent` | 8 | `build_release.py`, `DIAGNOSTIC_LOG.md`, `build_manual_pdf.py`, `README.md` |
| `aivrar/portable-hermes-agent` | 5 | `README.md`, `build_manual_pdf.py`, `DIAGNOSTIC_LOG.md` |
| `hermes-agent` | 8 | `README.md` |
| `nous research` | 2 | `README.md` |
| `nous` | **21** | `landingpage/index.html` |

### 7.2 Landing Page is Unbranded

The landing page (`landingpage/index.html`) has:
- Title: `"Hermes Agent — An Agent That Grows With You"` (generic)
- `nous` references: 21
- `SMF Works` references: **0**
- `aivrar` references: 0

This is the **most visible public artifact** and it's completely unbranded for SMF Works.

### 7.3 AGENTS.md Staleness

- **Does not reference `gui/`** — added 4/21, AGENTS.md is from upstream
- **Does not reference `skills/extensions/`** — added 4/22
- Remaining structures (`hermes_cli/`, `tools/`, `gateway/`) are accurate

### 7.4 What's Correctly Branded

- ✅ `pyproject.toml` → name `smf-forge-desktop`, authors include SMF Works
- ✅ `LICENSE` → dual copyright line (Nous Research + SMF Works)
- ✅ `build_manual_pdf.py` → confirmed SMF Works branding present

---

## 8. Recommendations (Prioritized)

### P0 — Critical (This Week)

1. **Restore SSRF protection** — Either merge upstream `browser_tool.py` + restore `url_safety.py`, or cherry-pick security commits properly.
2. **Fix `workflow_tool.py` `eval()`** — Replace with `ast.literal_eval` or a sandboxed expression parser.
3. **Rebrand landing page** — Replace all 21 `nous` references with SMF Works branding, rewrite title tag, update favicon and hero banner.
4. **Purge stale references** — Batch-replace `portable-hermes-agent` → `smf-windows-hermes`, purge `aivrar` URLs.

### P1 — High Priority (Next Sprint)

5. **Add `.gitignore` entries** — `build/`, `dist/`, `*.egg-info`, `.DS_Store`
6. **Add dev dependencies** — `pytest`, `pytest-cov`, `mypy`, `ruff`, `bandit`
7. **Create single-file Windows executable** — PyInstaller or `nuitka` build pipeline (`build_exe.bat` / `build_exe.ps1`)
8. **Windows installer** — Inno Setup or WiX `.msi` installer with Python runtime bundling
9. **Update AGENTS.md** — Add `gui/` and `skills/extensions/` sections, refresh architecture diagram

### P2 — Medium Priority (Next Month)

10. **Refactor monoliths** — Extract `run_agent.py` → `agent/` subpackage; extract `cli.py` → `cli/`
11. **Dockerfile** — Add lightweight container definition for testing
12. **CI/CD pipeline** — GitHub Actions workflow for pytest + lint + build verification
13. **Reduce duplicate code** — Extract gateway shared formatting into `gateway/platforms/common.py`
14. **DPI scaling audit** — Test Tkinter on 4K/HiDPI Windows displays; consider `ctypes` `SetProcessDpiAwareness` call in `.bat`

### P3 — Nice to Have

15. **Windows Terminal profile generator**
16. **Right-click context menu registration** (`.reg` file for "Open with SMF Forge Desktop")
17. **Code signing certificate** for `.exe` (prevents Windows SmartScreen warnings)

---

## 9. Quick-Reference Commands for Developers

```bash
# Clone (already done)
cd /home/mikesai2/smf-works/smf-windows-hermes

# Install editable in venv
python -m venv venv && source venv/bin/activate
pip install -e .

# Run linting (after adding deps)
ruff check . --select E,W,F
bandit -r . -ll

# Run tests
pytest tests/ --timeout=120 -x

# Build Windows executable (after adding PyInstaller)
pyinstaller --onefile --windowed gui/app.py --name "SMFForgeDesktop"
```

---

*Report generated by Liam Hermes (CDO, SMF Works) via automated codebase audit.*
