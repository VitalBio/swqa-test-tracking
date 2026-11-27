"""
The app's name, version and where its releases live.

Bump APP_VERSION for each release, then push a matching tag (v2.4.0); the release
build checks that they match.
"""


APP_TITLE   = "Test Tracker"
APP_VERSION = "2.6.1"         # bump this for each release, then push a matching tag (v2.4.0)
APP_CHANNEL = "stable"        # "stable" or "testing": testing releases are published as GitHub
                              # pre-releases, so the ⬆ Update button on stable copies never offers them
REFRESH_MS  = 60_000          # pull changes from the sheet every minute
REPO        = "VitalBio/swqa-test-tracking"
INSTALL_CMD = f"curl -fsSL https://raw.githubusercontent.com/{REPO}/main/install.sh | bash"
