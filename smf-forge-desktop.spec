# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for SMF Forge Desktop
# Produces a single-file GUI executable for Windows.

import os
import sys

base_path = os.path.abspath(SPECDIR)  # Set by PyInstaller at build time

# ---------------------------------------------------------------------------
# DYNAMIC IMPORT DISCOVERY
# PyInstaller can't trace importlib.import_module() calls; we register
# every top-level package we find so they are collected automatically.
# ---------------------------------------------------------------------------

def _walk_for_top_imports(root_path):
    """Find every package directory under root and add to hiddenimports."""
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune heavy / test / optional paths we didn't vendor
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith((".", "_", "node_modules", "__pycache__"))
            and d not in {"tests", "test", "landingpage", "website", "browser-use", "agent-browser", "optional-skills", "tinker-atropos", "mini-swe-agent"}
        ]
        if "__init__.py" in filenames:
            pkg = os.path.relpath(dirpath, root_path).replace(os.sep, ".")
            parts = []
            for seg in pkg.split("."):
                parts.append(seg)
                seen.add(".".join(parts))
    return sorted(seen)

# Core top-levels
pkg_imports = _walk_for_top_imports(base_path)

# Runtime dynamic imports (importlib, plugins, tools registry, model_tools, etc.)
_dynamic_imports = [
    "tools",
    "tools.registry",
    "model_tools",
    "utils",
    "batch_runner",
    "trajectory_compressor",
    "toolset_distributions",
    "hermes_cli",
    "hermes_cli.main",
    "hermes_cli.plugins",
    "hermes_cli.setup",
    "gateway",
    "gateway.hooks",
    "gateway.platforms",
    "gateway.platforms.api_server",
    "agent",
    "cron",
    "honcho_integration",
    "acp_adapter",
    "acp_adapter.entry",
    "mini_swe_runner",
    "run_agent",
    "cli",
    "hermes_constants",
    "hermes_state",
    "hermes_time",
]

# Optional heavy deps that may be conditionally loaded at runtime by the app.
# PyInstaller will ignore missing modules gracefully if not installed.
_optional_imports = [
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "httpx",
    "yaml",
    "openai",
    "anthropic",
    "rich",
    "jinja2",
    "pydantic",
    "dotenv",
    "prompt_toolkit",
    "tenacity",
    "requests",
    "fire",
    "edge_tts",
    "faster_whisper",
    "litellm",
    "typer",
    "fal_client",
    "firecrawl",
    "slack_bolt",
    "slack_sdk",
    "discord",
    "telegram",
    "aiohttp",
    "jwt",
    "platformdirs",
    "croniter",
]

hiddenimports = list(set(pkg_imports + _dynamic_imports + _optional_imports))

# ---------------------------------------------------------------------------
# DATA FILES
# Bundles non-Python assets that the runtime code reads from filesystem.
# ---------------------------------------------------------------------------

datas = [
    # Static assets (banner, icons, SOUL.md, etc.)
    (os.path.join(base_path, "assets"),         "assets"),
    # User-facing documentation (the app may reference these)
    (os.path.join(base_path, "docs"),            "docs"),
    # Gateway docs for platform integrators
    (os.path.join(base_path, "gateway"),         "gateway"),
    # ACP registry metadata
    (os.path.join(base_path, "acp_registry"),    "acp_registry"),
    # CLI themes / templates
    (os.path.join(base_path, "hermes_cli"),      "hermes_cli"),
    # Cron definitions
    (os.path.join(base_path, "cron"),            "cron"),
    # Honcho integration
    (os.path.join(base_path, "honcho_integration"), "honcho_integration"),
    # Data generation examples (optional but safe to include)
    (os.path.join(base_path, "datagen-config-examples"), "datagen-config-examples"),
    # Custom tool manifests
    (os.path.join(base_path, "tools"),           "tools"),
    # Optional custom tool metadata
    (os.path.join(base_path, "tools", "custom"), "tools/custom"),
    # Plans & archived specs (small text files)
    (os.path.join(base_path, "plans"),            "plans"),
    # Scripts directory (WhatsApp bridge, etc.)
    (os.path.join(base_path, "scripts"),         "scripts"),
    # Root-level markdown / config files referenced by the app
    (os.path.join(base_path, "README.md"),       "."),
    (os.path.join(base_path, "pyproject.toml"),    "."),
    (os.path.join(base_path, "requirements.txt"),  "."),
]

# Drop any paths that genuinely don't exist (optional deps not in tree)
datas = [(src, dst) for src, dst in datas if os.path.exists(src)]

# ---------------------------------------------------------------------------
# BINARIES (DLLs / shared libraries)
# tkinter / Tcl / Tk DLLs are automatically collected on Windows,
# but we force-include DLL directories in case PyInstaller misses them.
# ---------------------------------------------------------------------------

binaries = []

# ---------------------------------------------------------------------------
# ANALYSIS
# ---------------------------------------------------------------------------

a = Analysis(
    ["gui/app.py"],
    pathex=[base_path],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Bloated transitive deps we don't want inside the exe.
        # These are optional or only used in dev/tests.
        "pytest", "_pytest", "pytest_asyncio", "pytest_xdist",
        "black", "blib2to3", "mypy", "mypy_extensions",
        "jedi", "parso", "ipython", "IPython", "ipykernel",
        "matplotlib", "matplotlib.backends", "matplotlib.pyplot",
        "scipy", "scipy.special",
        "numpy.random._generator",      # faster-whisper uses numpy but not the RNG
        "torch.utils.tensorboard",
        "wandb", "tensorboard",
        "torchvision", "torchaudio",
        # Optional heavy NLP / transformer deps not needed for core GUI
        "transformers",
        "trl",
        "peft",
        "datasets",
        "tqdm.cli",
        # Docs / IDE tools
        "sphinx", "docutils",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,          # keep source in archive (smaller exe, slower boot)
    optimize=0,               # use Python -O if 2; 0 keeps asserts / __debug__
)

# ---------------------------------------------------------------------------
# EXCLUDE unnecessary large files PyInstaller may have pulled in
# ---------------------------------------------------------------------------

# Strip .pyc / __pycache__ from collected packages to reduce size
def _clean_pycache(toc):
    """Remove __pycache__ entries and .pyc duplicates."""
    seen = set()
    clean = []
    for name, path, typecode in toc:
        if "__pycache__" in name or name.endswith(".pyc"):
            continue
        key = name.lower().replace("\\", "/")
        if key in seen:
            continue
        seen.add(key)
        clean.append((name, path, typecode))
    return clean

a.pure = _clean_pycache(a.pure)

# ---------------------------------------------------------------------------
# PYD / binaries cleanup (leave alone — PyInstaller handles this well)
# ---------------------------------------------------------------------------

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXECUTABLE CONFIG
# ---------------------------------------------------------------------------

# Windows GUI app: console=False means no cmd window pops up.
# For CLI mode, set console=True (we provide a separate CLI spec if needed).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="smf-forge-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                # Compress with UPX if installed; harmless if absent.
    upx_exclude=["vcruntime140.dll"],
    runtime_tmpdir=None,    # Extract to temp dir (onefile default). Set a subfolder if you prefer persistence.
    console=False,            # GUI mode — no console window on Windows
    # If you have an icon file, uncomment and point to it:
    # icon=os.path.join(base_path, "assets", "icon.ico"),
    hide_console="hide-early",  # Avoid flash of console on startup
)
