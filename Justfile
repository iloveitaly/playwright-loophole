# GitHub recipes adapted from iloveitaly/python-package-template (see licenses/python-package-template-MIT.txt).
# Bash is available on GitHub Actions Ubuntu runners; no zsh dependency.
set shell := ["bash", "-euo", "pipefail", "-c"]
set script-interpreter := ["bash", "-euo", "pipefail"]
export GH_PAGER := "cat"

default:
    @just --list

# Build and run the end-to-end suite on a Linux Docker host (e.g. GitHub Actions).
test:
    python3 test/run.py

# Configure Actions permissions, metadata, squash merges, and default-branch protection.
github_setup: github_repo_permissions_create github_repo_set_metadata github_enforce_squash_merge github_ruleset_protect_default_create

[private]
_github_repo:
    @gh repo view --json nameWithOwner --jq .nameWithOwner

# Match the template's write/review permissions for future release automation.
github_repo_permissions_create:
    gh api --method PUT "repos/$(just _github_repo)/actions/permissions/workflow" \
        -f default_workflow_permissions=write \
        -F can_approve_pull_request_reviews=true
    gh api "repos/$(just _github_repo)/actions/permissions/workflow"

# This Docker project keeps repository metadata in metadata.json, not pyproject.toml.
[script]
github_repo_set_metadata:
    jq -e '.description | type == "string" and length > 0' metadata.json >/dev/null
    jq -e '.homepage | type == "string" and length > 0' metadata.json >/dev/null
    jq -e '.keywords | type == "array" and all(.[]; type == "string")' metadata.json >/dev/null
    repo=$(just _github_repo)
    gh repo edit "$repo" \
        --description "$(jq -r .description metadata.json)" \
        --homepage "$(jq -r .homepage metadata.json)"
    # Replace topics so removing a keyword also removes it on GitHub.
    jq '{names: .keywords}' metadata.json | gh api --method PUT "repos/$repo/topics" --input -

# Allow squash merges only and delete merged PR branches.
github_enforce_squash_merge:
    gh api --method PATCH "repos/$(just _github_repo)" \
        -F allow_squash_merge=true \
        -F allow_merge_commit=false \
        -F allow_rebase_merge=false \
        -F delete_branch_on_merge=true

# Idempotently create/update protection for the actual default branch (main or master).
[script]
github_ruleset_protect_default_create:
    repo=$(just _github_repo)
    branch=$(gh repo view "$repo" --json defaultBranchRef --jq .defaultBranchRef.name)
    if [ -z "$branch" ] || [ "$branch" = null ]; then
        echo "Push the initial branch before configuring its ruleset." >&2
        exit 1
    fi
    ruleset_name="Protect default branch from force pushes"
    ruleset_id=$(gh api --paginate "repos/$repo/rulesets" --jq ".[] | select(.name == \"$ruleset_name\") | .id")
    method=POST
    endpoint="repos/$repo/rulesets"
    if [ -n "$ruleset_id" ]; then
        method=PUT
        endpoint="$endpoint/$ruleset_id"
    fi
    jq -n --arg name "$ruleset_name" --arg branch "refs/heads/$branch" \
        '{name: $name, target: "branch", enforcement: "active", conditions: {ref_name: {include: [$branch], exclude: []}}, rules: [{type: "non_fast_forward"}]}' \
        | gh api --method "$method" "$endpoint" --input -

# Explicitly remove only the ruleset managed by this Justfile.
[script]
github_ruleset_protect_default_delete:
    repo=$(just _github_repo)
    ruleset_id=$(gh api --paginate "repos/$repo/rulesets" --jq '.[] | select(.name == "Protect default branch from force pushes") | .id')
    if [ -z "$ruleset_id" ]; then
        echo "No managed ruleset found."
        exit 0
    fi
    gh api --method DELETE "repos/$repo/rulesets/$ruleset_id"

# Show failed-job logs from the latest Build workflow on the current branch.
[script]
github_last_build_failure:
    branch=$(git branch --show-current)
    runs=$(gh run list --branch "$branch" --limit 20 --json databaseId,conclusion,status,workflowName)
    target=$(jq 'map(select(.workflowName | test("build"; "i"))) | .[0]' <<< "$runs")
    if [ "$target" = null ]; then
        echo "No Build workflows found for $branch."
    elif [ "$(jq -r .conclusion <<< "$target")" = success ]; then
        echo "Latest build succeeded."
    elif [ "$(jq -r .status <<< "$target")" != completed ]; then
        echo "Latest build is still running."
    else
        gh run view "$(jq -r .databaseId <<< "$target")" --log-failed
    fi

# Rerun failed jobs from the most recent failed Build workflow on this branch.
[script]
github_rerun_failed:
    branch=$(git branch --show-current)
    runs=$(gh run list --branch "$branch" --status failure --limit 20 --json databaseId,workflowName)
    id=$(jq -r 'map(select(.workflowName | test("build"; "i"))) | .[0].databaseId' <<< "$runs")
    if [ "$id" = null ]; then
        echo "No failed Build workflows found for $branch."
        exit 0
    fi
    gh run rerun "$id" --failed
