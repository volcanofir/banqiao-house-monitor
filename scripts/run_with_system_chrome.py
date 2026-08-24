"""Run a Python script while default Playwright Chromium launches use system Chrome.

GitHub-hosted Ubuntu runners already include Google Chrome. This avoids downloading a
separate Playwright Chromium build on every workflow run while leaving scripts that
explicitly select another browser/channel untouched.
"""

import runpy
import sys

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
    runpy.run_path(target, run_name="__main__")


if __name__ == "__main__":
    main()
