#!/usr/bin/env bash
# Build webhook-inspector Docker image and push to Artifact Registry.
#
# Usage: ./scripts/build_and_push.sh <project-id> [tag]
# Default tag: git short SHA.

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <project-id> [tag]}"
TAG="${2:-$(git rev-parse --short HEAD)}"
REGION="europe-west1"
REPO="webhook-inspector"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/webhook-inspector:${TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/webhook-inspector:latest"

echo "==> Configuring docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "==> Building image: $IMAGE"
docker build --platform=linux/amd64 -t "$IMAGE" -t "$IMAGE_LATEST" .

echo "==> Pushing $IMAGE..."
docker push "$IMAGE"
docker push "$IMAGE_LATEST"

echo "==> Done."
echo "Image: $IMAGE"
echo "Tag exported for terraform: $TAG"
