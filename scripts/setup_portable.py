#!/usr/bin/env python3
"""Download and configure portable tools for the QoE probe.

Cross-platform Python port of setup-portable.ps1.
Downloads Node.js, yt-dlp, and installs fast-cli, then patches fast-cli
to increase the navigation timeout, disable automation detection, and set
a realistic Chrome User-Agent.

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _system() -> str:
    """Return normalised OS name: 'windows', 'linux', or 'darwin'."""
    return platform.system().lower()


def _arch() -> str:
    """Return normalised architecture: 'x64' or 'arm64'."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x64"  # fallback


def _is_windows() -> bool:
    return _system() == "windows"


def _is_legacy_windows() -> bool:
    if not _is_windows():
        return False
    try:
        return sys.getwindowsversion().major < 10
    except (AttributeError, ValueError):
        try:
            rel = platform.release()
            return "2012" in rel or "8" in rel or "7" in rel
        except Exception:
            return False


def _exe(name: str) -> str:
    """Append .exe on Windows."""
    if _is_windows() and not name.endswith(".exe"):
        return name + ".exe"
    return name


# ---------------------------------------------------------------------------
# Download URLs
# ---------------------------------------------------------------------------

def _node_url(version: str) -> str:
    """Construct the Node.js download URL for the current platform."""
    sys_name = _system()
    arch = _arch()
    if sys_name == "windows":
        return f"https://nodejs.org/dist/{version}/node-{version}-win-{arch}.zip"
    if sys_name == "darwin":
        return f"https://nodejs.org/dist/{version}/node-{version}-darwin-{arch}.tar.gz"
    # linux
    return f"https://nodejs.org/dist/{version}/node-{version}-linux-{arch}.tar.xz"


def _ytdlp_url_default() -> str:
    sys_name = _system()
    base = "https://github.com/yt-dlp/yt-dlp/releases/latest/download"
    if sys_name == "windows":
        return f"{base}/yt-dlp.exe"
    if sys_name == "darwin":
        return f"{base}/yt-dlp_macos"
    return f"{base}/yt-dlp"


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    return ctx


def _download(url: str, dest: Path, *, label: str = "") -> None:
    """Download *url* to *dest* with a progress indicator."""
    if not url.lower().startswith(('http://', 'https://')):
        raise ValueError('Invalid URL scheme: URL must start with http:// or https://')
    tag = label or dest.name
    print(f"  Downloading {tag} ...")
    print(f"    {url}")
    ctx = _make_ssl_context()
    req = Request(url, headers={"User-Agent": "CX-Radar-setup/1.0"})
    with urlopen(req, context=ctx) as resp:  # nosec B310
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            total = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
    size_mb = total / (1024 * 1024)
    print(f"    Saved {size_mb:.1f} MB -> {dest}")


# ---------------------------------------------------------------------------
# Archive extraction
# ---------------------------------------------------------------------------

def _is_safe_path(base: Path, target: str) -> bool:
    """Check if the target path is safely within the base directory (Python 3.8 compatible)."""
    try:
        target_path = (base / target).resolve()
        base_path = base.resolve()
        common = os.path.commonpath([str(base_path), str(target_path)])
        return common == str(base_path)
    except ValueError:
        return False


def _extract_node_archive(archive_path: Path, dest_root: Path) -> None:
    """Extract a Node.js archive and flatten so node(.exe) sits in *dest_root*."""
    staging = archive_path.parent / (archive_path.stem.split(".")[0] + "-extract")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    name_lower = archive_path.name.lower()
    if name_lower.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.infolist():
                if _is_safe_path(staging, member.filename):
                    zf.extract(member, path=staging)
    elif name_lower.endswith(".tar.gz") or name_lower.endswith(".tar.xz"):
        with tarfile.open(archive_path, "r:*") as tf:
            for member in tf.getmembers():
                if _is_safe_path(staging, member.name):
                    tf.extract(member, path=staging)
    else:
        raise RuntimeError(f"Unsupported archive format: {archive_path.name}")

    # Find the node executable inside the extracted tree
    node_name = _exe("node")
    node_exe: Optional[Path] = None
    for candidate in staging.rglob(node_name):
        if candidate.is_file():
            node_exe = candidate
            break

    if node_exe is None:
        raise RuntimeError(
            f"Extracted archive '{archive_path.name}' does not contain {node_name}."
        )

    source_root = node_exe.parent

    # Replace destination with contents of the directory containing node
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    for item in source_root.iterdir():
        dest_item = dest_root / item.name
        if item.is_dir():
            shutil.copytree(item, dest_item)
        else:
            shutil.copy2(item, dest_item)

    shutil.rmtree(staging)


# ---------------------------------------------------------------------------
# Portable Node validation
# ---------------------------------------------------------------------------

def _test_portable_node(node_root: Path) -> bool:
    node_exe = node_root / _exe("node")
    if not node_exe.is_file():
        return False

    if _is_windows():
        npm_cmd = node_root / "npm.cmd"
    else:
        npm_cmd = node_root / "bin" / "npm"
        if not npm_cmd.is_file():
            npm_cmd = node_root / "npm"

    npm_cli = node_root / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_cli.is_file():
        # On Linux/macOS the layout may differ; check under lib/
        npm_cli = node_root / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"

    return npm_cmd.is_file() and npm_cli.is_file()


# ---------------------------------------------------------------------------
# fast-cli helpers
# ---------------------------------------------------------------------------

def _fast_cli_script_path(fast_cli_root: Path) -> Path:
    candidates = [
        fast_cli_root / "node_modules" / "fast-cli" / "cli.js",
        fast_cli_root / "node_modules" / "fast-cli" / "distribution" / "cli.js",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def _npm_command(node_root: Path) -> Path:
    """Return path to npm command."""
    if _is_windows():
        return node_root / "npm.cmd"
    # On Unix the npm wrapper might be in bin/ or in the root
    for candidate in (node_root / "bin" / "npm", node_root / "npm"):
        if candidate.is_file():
            return candidate
    return node_root / "bin" / "npm"


def _patch_fast_cli(fast_cli_script: Path) -> None:
    """Apply the same three patches as the PowerShell version."""
    api_js = fast_cli_script.parent / "api.js"
    if not api_js.is_file():
        return

    content = api_js.read_text(encoding="utf-8")
    modified = False

    # 1. Set a real Chrome User-Agent and set default navigation timeout
    if "setUserAgent" not in content:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        if "const page = await browser.newPage();" in content:
            content = content.replace(
                "const page = await browser.newPage();",
                f"const page = await browser.newPage();\n    await page.setUserAgent('{ua}');\n    await page.setDefaultNavigationTimeout(390000);"
            )
            modified = True

    # 2. Increase navigation timeout to 390 s (for versions using timeoutMs variable)
    if "timeoutMs" in content:
        new_content, n = re.subn(
            r"timeoutMs\s*=\s*(90000|240000|390000)",
            "timeoutMs = 390000",
            content,
        )
        if n:
            content = new_content
            modified = True

    # 3. Disable AutomationControlled blink feature and ignore certificate errors
    if "AutomationControlled" not in content:
        if "'--ignore-certificate-errors'" in content:
            content = content.replace(
                "'--ignore-certificate-errors'",
                "'--ignore-certificate-errors', '--disable-blink-features=AutomationControlled'",
            )
            modified = True
        elif "args: ['--no-sandbox']" in content:
            content = content.replace(
                "args: ['--no-sandbox']",
                "args: ['--no-sandbox', '--ignore-certificate-errors', '--disable-blink-features=AutomationControlled']",
            )
            modified = True

    if modified:
        api_js.write_text(content, encoding="utf-8")
        print("    Patched fast-cli api.js (timeout / automation / user-agent)")


def _test_fast_cli(node_root: Path, fast_cli_root: Path) -> bool:
    node_exe = node_root / _exe("node")
    script = _fast_cli_script_path(fast_cli_root)
    if not node_exe.is_file() or not script.is_file():
        return False
    try:
        result = subprocess.run(
            [str(node_exe), str(script), "--version"],
            cwd=str(fast_cli_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _install_fast_cli(
    node_root: Path,
    fast_cli_root: Path,
    version: str,
    puppeteer_cache: Path,
    npm_cache: Path,
    tmp_dir: Path,
) -> Path:
    """Install fast-cli via npm, with up to 2 attempts."""
    npm_cmd = _npm_command(node_root)
    if not npm_cmd.is_file():
        raise RuntimeError(f"Portable npm not found at {npm_cmd}")

    for d in (puppeteer_cache, npm_cache, tmp_dir):
        d.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PUPPETEER_CACHE_DIR"] = str(puppeteer_cache)
    env["PUPPETEER_TMP_DIR"] = str(tmp_dir)
    env["npm_config_cache"] = str(npm_cache)
    # Prepend node_root (and its bin/ on unix) to PATH
    if _is_windows():
        env["PATH"] = f"{node_root};{env.get('PATH', '')}"
    else:
        env["PATH"] = f"{node_root / 'bin'}:{node_root}:{env.get('PATH', '')}"

    last_exit = 0
    for attempt in range(1, 3):
        if fast_cli_root.exists():
            shutil.rmtree(fast_cli_root)
        fast_cli_root.mkdir(parents=True, exist_ok=True)

        # Write package.json with overrides to prevent string-width from using Unicode set regex (/v flag) which requires Node 20+
        import json
        package_json = {
            "name": "qoe-fast-cli-portable",
            "version": "1.0.0",
            "private": True,
            "dependencies": {
                "fast-cli": version
            },
            "overrides": {
                "string-width": "4.2.3",
                "yargs-parser": "20.2.9"
            }
        }
        try:
            (fast_cli_root / "package.json").write_text(json.dumps(package_json, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"    Warning: Failed to write package.json: {e}")

        print(f"    npm install fast-cli@{version} (attempt {attempt}) ...")
        result = subprocess.run(
            [
                str(npm_cmd), "install",
                "--no-fund", "--no-audit",
            ],
            cwd=str(fast_cli_root),
            env=env,
            capture_output=True,
            text=True,
        )
        last_exit = result.returncode

        script = _fast_cli_script_path(fast_cli_root)
        if script.is_file():
            _patch_fast_cli(script)
            if _test_fast_cli(node_root, fast_cli_root):
                return script

    if last_exit != 0:
        raise RuntimeError(
            f"npm install fast-cli@{version} failed with exit code {last_exit}."
        )
    raise RuntimeError(
        f"fast-cli entrypoint at '{_fast_cli_script_path(fast_cli_root)}' "
        f"did not pass a post-install validation run."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download portable tools for the QoE probe (cross-platform)."
    )
    parser.add_argument(
        "--bin-root",
        type=str,
        default="",
        help="Root directory for portable binaries (default: ../bin relative to this script).",
    )
    parser.add_argument(
        "--node-version",
        type=str,
        default="v20.20.2",
        help="Node.js version to download (default: v20.20.2).",
    )
    parser.add_argument(
        "--yt-dlp-url",
        type=str,
        default="",
        help="yt-dlp download URL (default: latest GitHub release for current OS).",
    )
    parser.add_argument(
        "--fast-cli-version",
        type=str,
        default="5.2.0",
        help="fast-cli npm package version (default: 5.2.0).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-install everything.",
    )
    args = parser.parse_args()

    # Automatically downgrade Node version and fast-cli version for legacy Windows platforms (Server 2012 / Win 7/8)
    if _is_legacy_windows():
        if args.node_version == "v20.20.2":
            print("[System Info] Legacy Windows detected. Falling back to Node.js v16.20.2 for compatibility.")
            args.node_version = "v16.20.2"
        if args.fast_cli_version == "5.2.0":
            print("[System Info] Legacy Windows detected. Falling back to fast-cli v3.2.0 for compatibility.")
            args.fast_cli_version = "3.2.0"

    # --- Paths ---
    script_dir = Path(__file__).resolve().parent
    if args.bin_root:
        bin_root = Path(args.bin_root).resolve()
    else:
        bin_root = (script_dir / ".." / "bin").resolve()

    downloads_dir = bin_root / "_downloads"
    node_root = bin_root / "node"
    fast_cli_root = bin_root / "fast-cli"
    yt_dlp_path = bin_root / _exe("yt-dlp")
    puppeteer_cache = bin_root / "puppeteer-cache"
    tmp_dir = bin_root / "tmp"
    npm_cache = bin_root / "npm-cache"

    bin_root.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Node.js
    # ------------------------------------------------------------------
    print("[1/3] Node.js")
    node_url = _node_url(args.node_version)
    archive_name = node_url.rsplit("/", 1)[-1]
    archive_path = downloads_dir / archive_name

    if args.force or not _test_portable_node(node_root):
        if not archive_path.is_file():
            _download(node_url, archive_path, label="Node.js")
        print(f"  Extracting to {node_root} ...")
        _extract_node_archive(archive_path, node_root)
    else:
        print("  Portable Node.js already installed — skipping.")

    # Clean up archive
    if archive_path.is_file():
        archive_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # 2. yt-dlp
    # ------------------------------------------------------------------
    print("[2/3] yt-dlp")
    ytdlp_url = args.yt_dlp_url or _ytdlp_url_default()

    if args.force or not yt_dlp_path.is_file():
        _download(ytdlp_url, yt_dlp_path, label="yt-dlp")
        if not _is_windows():
            # Make executable on Unix
            yt_dlp_path.chmod(yt_dlp_path.stat().st_mode | 0o755)
    else:
        print("  yt-dlp already present — skipping.")

    # ------------------------------------------------------------------
    # 3. fast-cli
    # ------------------------------------------------------------------
    print("[3/3] fast-cli")

    if args.force and fast_cli_root.exists():
        shutil.rmtree(fast_cli_root)

    fast_cli_script = _fast_cli_script_path(fast_cli_root)

    if args.force or not _test_fast_cli(node_root, fast_cli_root):
        fast_cli_script = _install_fast_cli(
            node_root=node_root,
            fast_cli_root=fast_cli_root,
            version=args.fast_cli_version,
            puppeteer_cache=puppeteer_cache,
            npm_cache=npm_cache,
            tmp_dir=tmp_dir,
        )
    else:
        print("  fast-cli already installed and validated — skipping.")
        _patch_fast_cli(fast_cli_script)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    node_exe_path = node_root / _exe("node")
    npm_cmd_path = _npm_command(node_root)

    max_label = 24
    summary = {
        "BinRoot": str(bin_root),
        "NodeExe": str(node_exe_path),
        "NpmCmd": str(npm_cmd_path),
        "FastCliRoot": str(fast_cli_root),
        "FastCliScript": str(fast_cli_script),
        "YtDlpExe": str(yt_dlp_path),
        "PuppeteerCacheDir": str(puppeteer_cache),
        "TemporaryDirectory": str(tmp_dir),
    }
    for key, value in summary.items():
        print(f"{key:<{max_label}} : {value}")


if __name__ == "__main__":
    main()
