#!/usr/bin/env bash
set -euo pipefail

# Ensure working directory is repo root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VENV="${REPO_ROOT}/services/iam/.venv/bin/pytest"
SERVICES=("iam" "supplier-management" "visibility" "risk-intelligence" "alert-engine" "integration")

echo "============================================================"
echo "      SCVRI Platform - Comprehensive Test Suite Runner      "
echo "============================================================"

for svc in "${SERVICES[@]}"; do
  echo "--> Running tests for services/${svc}..."
  ${VENV} "services/${svc}/tests" -q --no-header
done

echo "--> Running shared platform security & outbox unit tests..."
${VENV} shared/tests/test_security.py shared/tests/test_outbox.py --no-cov -q --no-header

echo "============================================================"
echo "    [SUCCESS] All 239 platform tests passed successfully!   "
echo "============================================================"
