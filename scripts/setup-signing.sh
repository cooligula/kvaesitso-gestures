#!/usr/bin/env bash
# One-time signing setup for this repository, for macOS or Linux. Needs openssl and the gh CLI.
#   scripts/setup-signing.sh [owner/repo]
# Reuses the signing key you already use for your other apps (default ~/.losforgos-keystore,
# override with KVG_KEYDIR) so that every app of yours is signed by the same certificate.
# It never creates a key. It then:
#   - creates the `release` environment (main branch only) with the four signing secrets
#   - sets the CERT_SHA256 variable, which makes the release job refuse any other key
#   - lets Actions open pull requests (the bump workflow needs it)
# Safe to run again.
set -euo pipefail

repo="${1:-}"
if [ -z "$repo" ]; then
  repo="$(git config --get remote.origin.url | sed -E 's#^.*github\.com[:/]##; s#\.git$##')"
fi
[ -n "$repo" ] || { echo "Pass the repository as owner/name" >&2; exit 1; }
echo "Repository: $repo"

dir="${KVG_KEYDIR:-$HOME/.losforgos-keystore}"
ks="$dir/losforgos.p12"
pwfile="$dir/password.txt"
[ -r "$ks" ] && [ -r "$pwfile" ] || {
  echo "No existing key found in $dir (need losforgos.p12 and password.txt)." >&2
  echo "This script reuses your existing key and never creates one." >&2
  exit 1
}
alias_name="${KVG_KEY_ALIAS:-losforgos}"

command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
command -v gh >/dev/null || { echo "Install the GitHub CLI (https://cli.github.com) first" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || gh auth login

pw="$(cat "$pwfile")"
cert="$(mktemp)"; trap 'rm -f "$cert"' EXIT
openssl pkcs12 -in "$ks" -passin "pass:$pw" -clcerts -nokeys -out "$cert" 2>/dev/null
sha="$(openssl x509 -in "$cert" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':')"
echo "Certificate SHA-256: $sha"

echo "Configuring $repo ..."
gh api -X PUT "repos/$repo/environments/release" \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true' >/dev/null
gh api -X POST "repos/$repo/environments/release/deployment-branch-policies" \
  -f name=main -f type=branch >/dev/null 2>&1 || true

base64 < "$ks" | tr -d '\n' | gh secret set KEYSTORE_B64 --env release --repo "$repo"
gh secret set KEYSTORE_PASSWORD --env release --repo "$repo" --body "$pw"
gh secret set KEY_ALIAS --env release --repo "$repo" --body "$alias_name"
gh secret set KEY_PASSWORD --env release --repo "$repo" --body "$pw"
gh variable set CERT_SHA256 --repo "$repo" --body "$sha"

gh api -X PUT "repos/$repo/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true >/dev/null

cat <<MSG

Done. The release environment, secrets and CERT_SHA256 are set on $repo.
The first release is published by the build workflow when the first pull request is merged, or with:
  gh workflow run build.yml --repo $repo --ref main -f release=true -f force=true
MSG
