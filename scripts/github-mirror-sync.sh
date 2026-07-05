#!/bin/bash
# Mirror all repos from a GitHub account to /home/claude/repos/
# Run periodically via systemd timer to discover new repos.
# Existing repos get webhooks for instant push-based sync.

set -euo pipefail

REPOS_DIR="/home/claude/repos"
GITHUB_OWNER="${GITHUB_OWNER:-your-github-username}"
WEBHOOK_URL="${WEBHOOK_URL:-https://your-hub-domain/webhooks/github}"
LOG_TAG="github-mirror"

log() { echo "[$(date -Iseconds)] $1"; }

# Require gh CLI authenticated
if ! gh auth status &>/dev/null; then
    log "ERROR: gh CLI not authenticated"
    exit 1
fi

# Get webhook secret from env file
WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-}"
if [ -z "$WEBHOOK_SECRET" ]; then
    # Try loading from service env file
    if [ -f /etc/claude-hub/claude-hub.env ]; then
        WEBHOOK_SECRET=$(grep '^GITHUB_WEBHOOK_SECRET=' /etc/claude-hub/claude-hub.env | cut -d= -f2-)
    fi
fi

mkdir -p "$REPOS_DIR"

# List all repos (handles pagination automatically)
log "Fetching repo list for $GITHUB_OWNER..."
repos=$(gh repo list "$GITHUB_OWNER" --limit 200 --json name --jq '.[].name')

cloned=0
pulled=0
failed=0
webhooks_added=0

for repo in $repos; do
    repo_path="$REPOS_DIR/$repo"

    if [ -d "$repo_path/.git" ]; then
        # Already cloned — pull latest
        if git -C "$repo_path" pull --ff-only &>/dev/null; then
            pulled=$((pulled + 1))
        else
            # ff-only failed, try reset to remote (read-only mirror, safe to reset)
            default_branch=$(git -C "$repo_path" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "main")
            if git -C "$repo_path" fetch origin &>/dev/null && git -C "$repo_path" reset --hard "origin/$default_branch" &>/dev/null; then
                pulled=$((pulled + 1))
            else
                log "WARN: Failed to sync $repo"
                failed=$((failed + 1))
            fi
        fi
    else
        # New repo — clone it
        log "Cloning $repo..."
        if gh repo clone "$GITHUB_OWNER/$repo" "$repo_path" -- --quiet 2>/dev/null; then
            cloned=$((cloned + 1))

            # Set up webhook for instant sync on future pushes
            if [ -n "$WEBHOOK_SECRET" ]; then
                # Check if webhook already exists
                existing=$(gh api "repos/$GITHUB_OWNER/$repo/hooks" --jq "[.[] | select(.config.url == \"$WEBHOOK_URL\")] | length" 2>/dev/null || echo "0")
                if [ "$existing" = "0" ]; then
                    if echo "{\"name\":\"web\",\"config\":{\"url\":\"$WEBHOOK_URL\",\"content_type\":\"json\",\"secret\":\"$WEBHOOK_SECRET\"},\"events\":[\"push\"],\"active\":true}" | \
                       gh api "repos/$GITHUB_OWNER/$repo/hooks" --method POST --input - &>/dev/null; then
                        webhooks_added=$((webhooks_added + 1))
                        log "  + webhook added for $repo"
                    else
                        log "  WARN: failed to add webhook for $repo"
                    fi
                fi
            fi
        else
            log "WARN: Failed to clone $repo"
            failed=$((failed + 1))
        fi
    fi
done

log "Sync complete: $cloned cloned, $pulled pulled, $webhooks_added webhooks added, $failed failed ($(echo "$repos" | wc -w) total)"
