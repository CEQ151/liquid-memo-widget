# Single source of truth for the app version. The release workflow rewrites
# APP_VERSION from the pushed tag before building, so a tagged build always
# reports the tag's version.

APP_VERSION = "2.0.2"

GITHUB_OWNER = "CEQ151"
GITHUB_REPO = "liquid-memo-widget"
GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
