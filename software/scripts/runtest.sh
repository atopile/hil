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

trap 'cleanup' EXIT

function cleanup() {
    if [ "${lock_obtained:-false}" = true ]; then
        echo "Cleaning up..."
        release_lock || true
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

    if ! rsync -aPh --exclude=.git/ --exclude-from=./.gitignore --delete "${PWD}/" "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}:${controller_path}/"; then
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
        uv run pytest $*
    ) 9>'${LOCK_FILE}'"
    ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "${SSH_COMMAND}"
    status=$?

    # enforce interval between test executions
    sleep 1

    return $status
}

check_ssh_connection || exit 1
verify_in_git_repo || exit 1
copy_to_controller || exit 1

run_test "$@"
status=$?

exit $status
