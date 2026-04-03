#!/usr/bin/env bash
##############################################################################
# deploy.sh — Build Lambda deployment package + Docker image, push to AWS
#
# Usage:
#   ./deploy.sh                    # Full deploy (Lambda + Docker)
#   ./deploy.sh lambda             # Lambda only
#   ./deploy.sh docker             # Docker only
#
# Prerequisites:
#   - AWS CLI configured with ramuponu-admin profile
#   - Docker installed (for Fargate deployment)
#   - mwinit completed
##############################################################################

set -euo pipefail

PROFILE="ramuponu-admin"
REGION="us-west-1"
STACK_NAME="openclaw-market-intel"
ACCOUNT_ID="073369242087"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/openclaw-market-intel"

MODE="${1:-all}"

echo "=== OpenClaw Deploy — mode: ${MODE} ==="

# ---------------------------------------------------------------------------
# Lambda deployment package
# ---------------------------------------------------------------------------
deploy_lambda() {
    echo ""
    echo "📦 Building Lambda deployment package..."

    DEPLOY_DIR="$(mktemp -d)"
    PACKAGE_DIR="${DEPLOY_DIR}/package"
    ZIP_FILE="${DEPLOY_DIR}/lambda-package.zip"

    mkdir -p "${PACKAGE_DIR}"

    # Install dependencies into package dir (Lambda-compatible)
    pip install \
        --platform manylinux2014_x86_64 \
        --target "${PACKAGE_DIR}" \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        --upgrade \
        yfinance requests fredapi beautifulsoup4 python-dotenv numpy pandas boto3 2>&1 | tail -5

    # Copy application code
    echo "📁 Copying application code..."
    cp -r agents "${PACKAGE_DIR}/"
    cp -r lambda_handlers "${PACKAGE_DIR}/"
    cp -r shared_memory "${PACKAGE_DIR}/"
    cp -r broker "${PACKAGE_DIR}/"

    # Copy top-level modules
    for f in shared_memory_io.py config.py tracker.py weight_adjuster.py \
             horizon_manager.py notifier.py email_formatter.py thesis_writer.py \
             rate_limiter.py daily_movers.py; do
        [ -f "$f" ] && cp "$f" "${PACKAGE_DIR}/"
    done

    # Create the zip
    echo "🗜️  Creating zip..."
    (cd "${PACKAGE_DIR}" && zip -r9 "${ZIP_FILE}" . -x '*.pyc' '__pycache__/*' '*.egg-info/*') > /dev/null

    ZIP_SIZE=$(du -sh "${ZIP_FILE}" | cut -f1)
    echo "   Package size: ${ZIP_SIZE}"

    # Upload to S3 (Lambda zip > 50MB needs S3)
    ZIP_BYTES=$(stat -f%z "${ZIP_FILE}" 2>/dev/null || stat -c%s "${ZIP_FILE}" 2>/dev/null)
    
    if [ "${ZIP_BYTES}" -gt 52428800 ]; then
        echo "📤 Package > 50MB — uploading to S3..."
        BUCKET="${STACK_NAME}-deploy-${ACCOUNT_ID}"
        aws s3 mb "s3://${BUCKET}" --profile "${PROFILE}" --region "${REGION}" 2>/dev/null || true
        aws s3 cp "${ZIP_FILE}" "s3://${BUCKET}/lambda-package.zip" \
            --profile "${PROFILE}" --region "${REGION}"

        echo "🔄 Updating Morning Analysis Lambda..."
        aws lambda update-function-code \
            --function-name "${STACK_NAME}-morning-analysis" \
            --s3-bucket "${BUCKET}" \
            --s3-key "lambda-package.zip" \
            --profile "${PROFILE}" --region "${REGION}" \
            --output text --query 'FunctionArn'

        echo "🔄 Updating EOD Recap Lambda..."
        aws lambda update-function-code \
            --function-name "${STACK_NAME}-eod-recap" \
            --s3-bucket "${BUCKET}" \
            --s3-key "lambda-package.zip" \
            --profile "${PROFILE}" --region "${REGION}" \
            --output text --query 'FunctionArn'
    else
        echo "🔄 Updating Morning Analysis Lambda (direct upload)..."
        aws lambda update-function-code \
            --function-name "${STACK_NAME}-morning-analysis" \
            --zip-file "fileb://${ZIP_FILE}" \
            --profile "${PROFILE}" --region "${REGION}" \
            --output text --query 'FunctionArn'

        echo "🔄 Updating EOD Recap Lambda (direct upload)..."
        aws lambda update-function-code \
            --function-name "${STACK_NAME}-eod-recap" \
            --zip-file "fileb://${ZIP_FILE}" \
            --profile "${PROFILE}" --region "${REGION}" \
            --output text --query 'FunctionArn'
    fi

    # Cleanup
    rm -rf "${DEPLOY_DIR}"
    echo "✅ Lambda functions updated"
}

# ---------------------------------------------------------------------------
# Docker image build + push
# ---------------------------------------------------------------------------
deploy_docker() {
    echo ""
    echo "🐳 Building Docker image..."

    # ECR login
    aws ecr get-login-password --profile "${PROFILE}" --region "${REGION}" \
        | docker login --username AWS --password-stdin "${ECR_URI}"

    # Build
    docker build -t openclaw-market-intel .

    # Tag + push
    docker tag openclaw-market-intel:latest "${ECR_URI}:latest"
    docker push "${ECR_URI}:latest"

    echo "🔄 Updating Fargate service..."
    aws ecs update-service \
        --cluster "${STACK_NAME}-cluster" \
        --service "${STACK_NAME}-service" \
        --force-new-deployment \
        --profile "${PROFILE}" --region "${REGION}" \
        --output text --query 'service.serviceName'

    echo "✅ Docker image pushed + Fargate service updated"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${MODE}" in
    lambda)  deploy_lambda ;;
    docker)  deploy_docker ;;
    all)     deploy_lambda; deploy_docker ;;
    *)       echo "Usage: $0 [lambda|docker|all]"; exit 1 ;;
esac

echo ""
echo "=== Deploy complete ==="
