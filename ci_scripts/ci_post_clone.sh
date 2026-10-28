#!/bin/sh
# Xcode Cloud post-clone script.
# Place this file at: <repo root>/ci_scripts/ci_post_clone.sh
# Then run once locally: chmod +x ci_scripts/ci_post_clone.sh && git add --chmod=+x ci_scripts/ci_post_clone.sh
#
# Define these in the Xcode Cloud workflow under Environment -> Environment Variables:
#   SPOTIFY_CLIENT_ID      (required; not secret with PKCE, but keep it out of git)
#   SPOTIFY_REDIRECT_HOST  (optional; defaults to "callback" for playlistsync://callback)
#   BACKEND_API_KEY        (optional; only if you add your own backend. Mark as Secret)

set -e

echo "== ci_post_clone: start =="

if [ -z "$SPOTIFY_CLIENT_ID" ]; then
  echo "error: SPOTIFY_CLIENT_ID is not set in the Xcode Cloud workflow environment." >&2
  exit 1
fi

CONFIG_FILE="$CI_PRIMARY_REPOSITORY_PATH/Secrets.xcconfig"

{
  echo "SPOTIFY_CLIENT_ID = $SPOTIFY_CLIENT_ID"
  echo "SPOTIFY_REDIRECT_HOST = ${SPOTIFY_REDIRECT_HOST:-callback}"
  if [ -n "$BACKEND_API_KEY" ]; then
    echo "BACKEND_API_KEY = $BACKEND_API_KEY"
  fi
} > "$CONFIG_FILE"

echo "Wrote Secrets.xcconfig (values not printed)."

# Uncomment if you use CocoaPods or Homebrew-installed tools:
# brew install swiftlint
# pod install --repo-update

echo "== ci_post_clone: done =="
