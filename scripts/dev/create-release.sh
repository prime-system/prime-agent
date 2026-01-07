#!/usr/bin/env bash
#
# Create a new release for prime-agent
#
# Usage:
#   ./scripts/create-release.sh <version> [--push]
#
# Examples:
#   ./scripts/create-release.sh 0.2.0          # Create release v0.2.0 (no push)
#   ./scripts/create-release.sh 0.2.0 --push   # Create and push release v0.2.0
#   ./scripts/create-release.sh 1.0.0-beta.1   # Create pre-release v1.0.0-beta.1
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PYPROJECT_FILE="pyproject.toml"
REQUIRED_BRANCH="main"

# Functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

show_usage() {
    cat << EOF
Usage: $0 <version> [--push]

Create a new release by updating pyproject.toml, committing, and tagging.

Arguments:
  version     Semantic version number (e.g., 0.2.0, 1.0.0-beta.1)
  --push      Automatically push commit and tag to remote (optional)

Examples:
  $0 0.2.0                  # Create release v0.2.0 locally
  $0 0.2.0 --push           # Create and push release v0.2.0
  $0 1.0.0-beta.1           # Create pre-release v1.0.0-beta.1
  $0 1.0.0-rc.1 --push      # Create and push release candidate

Semantic Versioning:
  MAJOR.MINOR.PATCH[-PRERELEASE]

  - PATCH (0.1.0 → 0.1.1): Bug fixes, minor improvements
  - MINOR (0.1.0 → 0.2.0): New features, backwards compatible
  - MAJOR (0.1.0 → 1.0.0): Breaking changes, API redesign
  - PRERELEASE: alpha, beta, rc (e.g., 1.0.0-beta.1)

What this script does:
  1. Validates version format and git state
  2. Checks you're on the main branch
  3. Ensures working directory is clean
  4. Updates version in pyproject.toml
  5. Commits the version bump
  6. Creates annotated git tag
  7. Optionally pushes to remote

After running, the GitHub Actions release workflow will:
  - Validate version matches tag
  - Build multi-arch Docker images
  - Publish to GitHub Container Registry
  - Create GitHub Release with changelog
EOF
}

validate_semver() {
    local version=$1
    # Validate semantic versioning format: MAJOR.MINOR.PATCH[-PRERELEASE]
    if ! [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9\.]+)?$ ]]; then
        log_error "Invalid version format: $version"
        log_error "Expected format: MAJOR.MINOR.PATCH[-PRERELEASE]"
        log_error "Examples: 0.2.0, 1.0.0, 1.0.0-beta.1, 2.1.0-rc.2"
        return 1
    fi
    return 0
}

check_git_status() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        log_error "Not inside a git repository"
        return 1
    fi

    # Check if we're on the required branch
    current_branch=$(git branch --show-current)
    if [ "$current_branch" != "$REQUIRED_BRANCH" ]; then
        log_error "Not on $REQUIRED_BRANCH branch (currently on: $current_branch)"
        log_error "Please switch to $REQUIRED_BRANCH: git checkout $REQUIRED_BRANCH"
        return 1
    fi

    # Check for uncommitted changes
    if ! git diff-index --quiet HEAD --; then
        log_error "Working directory has uncommitted changes"
        log_error "Please commit or stash your changes before creating a release"
        git status --short
        return 1
    fi

    return 0
}

check_tag_exists() {
    local tag=$1
    if git rev-parse "$tag" >/dev/null 2>&1; then
        log_error "Tag $tag already exists"
        log_error "Delete it first with: git tag -d $tag"
        return 1
    fi
    return 0
}

get_current_version() {
    if ! [ -f "$PYPROJECT_FILE" ]; then
        log_error "Cannot find $PYPROJECT_FILE"
        return 1
    fi

    # Extract version from pyproject.toml using Python
    python3 -c "
import tomllib
with open('$PYPROJECT_FILE', 'rb') as f:
    data = tomllib.load(f)
    print(data['project']['version'])
" 2>/dev/null || {
        log_error "Failed to read version from $PYPROJECT_FILE"
        return 1
    }
}

update_version() {
    local new_version=$1

    log_info "Updating version in $PYPROJECT_FILE to $new_version..."

    # Use sed to update version in pyproject.toml
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/^version = \".*\"/version = \"$new_version\"/" "$PYPROJECT_FILE"
    else
        # Linux
        sed -i "s/^version = \".*\"/version = \"$new_version\"/" "$PYPROJECT_FILE"
    fi

    # Verify the update
    local updated_version
    updated_version=$(get_current_version)
    if [ "$updated_version" != "$new_version" ]; then
        log_error "Failed to update version in $PYPROJECT_FILE"
        log_error "Expected: $new_version, Got: $updated_version"
        return 1
    fi

    log_success "Updated $PYPROJECT_FILE to version $new_version"
    return 0
}

create_release() {
    local version=$1
    local should_push=$2
    local tag="v$version"

    log_info "Creating release $tag..."
    echo ""

    # Get current version
    local current_version
    current_version=$(get_current_version)
    log_info "Current version: $current_version"
    log_info "New version: $version"
    echo ""

    # Check if this is a pre-release
    local release_type="stable release"
    if [[ $version =~ -(alpha|beta|rc) ]]; then
        release_type="pre-release"
    fi
    log_info "Release type: $release_type"
    echo ""

    # Validate inputs
    log_info "Validating version format..."
    if ! validate_semver "$version"; then
        return 1
    fi
    log_success "Version format valid"

    log_info "Checking git status..."
    if ! check_git_status; then
        return 1
    fi
    log_success "Git status clean"

    log_info "Checking if tag $tag exists..."
    if ! check_tag_exists "$tag"; then
        return 1
    fi
    log_success "Tag $tag available"
    echo ""

    # Update version in pyproject.toml
    if ! update_version "$version"; then
        return 1
    fi
    echo ""

    # Commit the version bump
    log_info "Committing version bump..."
    git add "$PYPROJECT_FILE"
    git commit -m "chore: bump version to $version"
    log_success "Committed version bump"

    # Create annotated tag
    log_info "Creating annotated tag $tag..."
    git tag -a "$tag" -m "Release $tag"
    log_success "Created tag $tag"
    echo ""

    # Show what was done
    log_success "Release $tag created successfully!"
    echo ""
    echo "Summary:"
    echo "  • Updated $PYPROJECT_FILE: $current_version → $version"
    echo "  • Created commit: $(git rev-parse --short HEAD)"
    echo "  • Created tag: $tag"
    echo ""

    # Push if requested
    if [ "$should_push" = true ]; then
        log_info "Pushing commit and tag to remote..."
        git push origin "$REQUIRED_BRANCH"
        git push origin "$tag"
        log_success "Pushed to remote"
        echo ""
        echo "✨ Release workflow will now run automatically!"
        echo ""
        echo "Monitor progress at:"
        echo "  https://github.com/$(git config --get remote.origin.url | sed 's/.*github.com[:/]\(.*\)\.git/\1/')/actions"
    else
        log_warning "Changes not pushed to remote (use --push to push automatically)"
        echo ""
        echo "To push manually, run:"
        echo "  git push origin $REQUIRED_BRANCH"
        echo "  git push origin $tag"
    fi

    echo ""
    echo "Docker images will be published as:"
    echo "  • ghcr.io/YOUR_USERNAME/prime-agent:$version"
    echo "  • ghcr.io/YOUR_USERNAME/prime-agent:${version%.*}"
    echo "  • ghcr.io/YOUR_USERNAME/prime-agent:${version%%.*}"
    if [ "$release_type" = "stable release" ]; then
        echo "  • ghcr.io/YOUR_USERNAME/prime-agent:latest"
    fi
    echo "  • ghcr.io/YOUR_USERNAME/prime-agent:sha-XXXXXXX"
    echo ""

    return 0
}

# Main script
main() {
    # Parse arguments
    if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
        show_usage
        exit 0
    fi

    local version=$1
    local should_push=false

    if [ $# -ge 2 ] && [ "$2" = "--push" ]; then
        should_push=true
    fi

    # Create the release
    if create_release "$version" "$should_push"; then
        exit 0
    else
        log_error "Failed to create release"
        exit 1
    fi
}

main "$@"
