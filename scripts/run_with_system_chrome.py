"""Run a Python script while default Playwright Chromium launches use system Chrome.

GitHub-hosted Ubuntu runners already include Google Chrome. This avoids downloading a
separate Playwright Chromium build on every workflow run while leaving scripts that
explicitly select another browser/channel untouched.
"""

import runpy
import sys
from pathlib import Path

from playwright.sync_api import BrowserType


_original_launch = BrowserType.launch


def _launch_with_system_chrome(self, *args, **kwargs):
    if not kwargs.get("channel") and not kwargs.get("executable_path"):
        kwargs["channel"] = "chrome"
    return _original_launch(self, *args, **kwargs)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_with_system_chrome.py <script.py> [args...]")
    target = sys.argv[1]
    target_args = sys.argv[2:]
    BrowserType.launch = _launch_with_system_chrome
    sys.argv = [target, *target_args]
    try:
        runpy.run_path(target, run_name="__main__")
    except BaseException as exc:
        if target.endswith("smoke_test_preview_ui.py"):
            try:
                log = Path("docs/preview/yungching-preview-run.log")
                with log.open("a", encoding="utf-8") as f:
                    f.write(f"\nPREVIEW_SMOKE_ERROR {type(exc).__name__}: {exc}\n")
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
