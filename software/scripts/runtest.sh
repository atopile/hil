#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${HIL_CONTROLLER_HOST:-}" ]]; then
    echo "ERROR: HIL_CONTROLLER_HOST environment variable must be set"
    echo "Example: HIL_CONTROLLER_HOST=chunky-otter $0"
    exit 1
fi

CONTROLLER_HOST="${HIL_CONTROLLER_HOST}"
CONTROLLER_USERNAME='atopile'

LOCK_FILE="/home/atopile/.hil-lock"
CONTROLLER_PATH_PREFIX="/home/atopile/hil/"
LOCK_TIMEOUT=120
TEST_REPORT_PORT=8080
TMP_DIR=$(mktemp -d)

trap 'cleanup' EXIT

function cleanup() {
    if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
        rm -rf "${TMP_DIR}"
    fi
}

function get_controller_path() {
    local username=$(whoami)
    local hostname=$(hostname)
    echo "${CONTROLLER_PATH_PREFIX}/${username}@${hostname}"
}

function verify_in_git_repo() {
    if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
        echo "ERROR: Not in a git repository"
        return 1
    fi
}

function check_ssh_connection() {
    if ! ssh -q "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "exit" 2>/dev/null; then
        echo "ERROR: Cannot connect to controller at ${CONTROLLER_USERNAME}@${CONTROLLER_HOST}"
        return 1
    fi
}

function copy_to_controller() {
    local controller_path=$(get_controller_path)

    if ! ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "mkdir -p '${controller_path}'"; then
        echo "ERROR: Failed to create target directory on controller"
        return 1
    fi

    local rsync_exclude="--exclude=.git/ --exclude-from=./.gitignore"
    if [ -f ".hilignore" ]; then
        rsync_exclude+=" --exclude-from=./.hilignore"
    fi

    if ! rsync -aPh ${rsync_exclude} --delete "${PWD}/" "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}:${controller_path}/"; then
        echo "ERROR: Failed to copy files to controller"
        return 1
    fi
}

function uv_sync() {
    local controller_path=$(get_controller_path)

    if ! ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "cd '${controller_path}' && uv sync"; then
        echo "ERROR: uv sync failed"
        return 1
    fi
}

function run_test() {
    local controller_path=$(get_controller_path)
    SSH_COMMAND="cd '${controller_path}' && (
        flock --exclusive --timeout ${LOCK_TIMEOUT} 9 || { echo 'ERROR: Failed to acquire lock in time'; exit 1; }
        uv run pytest $* && sleep 1
    ) 9>'${LOCK_FILE}'"
    ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "${SSH_COMMAND}"
    status=$?

    return $status
}

function serve_test_report() {
    local controller_path=$(get_controller_path)
    scp -r -q "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}:${controller_path}/artifacts/*" "${TMP_DIR}"
    echo "Serving test report at http://127.0.0.1:8080/test-report.html"
    python3 -m http.server --directory "${TMP_DIR}" --bind 127.0.0.1 "${TEST_REPORT_PORT}" >/dev/null 2>&1
}

check_ssh_connection || exit 1
verify_in_git_repo || exit 1
copy_to_controller || exit 1

set +e
run_test "$@"
status=$?
set -e

serve_test_report || true

exit "$status"
