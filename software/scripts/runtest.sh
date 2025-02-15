#!/usr/bin/env bash

set -euo pipefail

# TODO: via CLI args
CONTROLLER_USERNAME='atopile'
CONTROLLER_HOST="chunky-otter"

LOCK_FILE="/home/atopile/.hil-lock"
CONTROLLER_PATH_PREFIX="/home/atopile/hil/"

trap 'cleanup' EXIT

function cleanup() {
    if [ "${lock_obtained:-false}" = true ]; then
        echo "Cleaning up..."
        release_lock || true
    fi
}

function get_lock_contents() {
    local username=$(whoami)
    local hostname=$(hostname)
    echo "$username@$hostname"
}

function get_controller_path() {
    local username=$(whoami)
    local hostname=$(hostname)
    echo "${CONTROLLER_PATH_PREFIX}/${username}@${hostname}"
}

function obtain_lock() {
    local lock_contents=$(get_lock_contents)
    local max_attempts=60  # 5 minutes with 5 second sleep
    local attempt=1

    echo "Attempting to obtain lock..."

    while [ $attempt -le $max_attempts ]; do
        # TOOD: atomic?
        if ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "[ ! -f '${LOCK_FILE}' ] && echo '${lock_contents}' > '${LOCK_FILE}'" 2>/dev/null; then
            echo "Lock obtained"
            return 0
        fi

        local current_owner
        current_owner=$(ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "cat '${LOCK_FILE}'" 2>/dev/null) || {
            echo "ERROR: Cannot read lock file"
            return 1
        }
        echo "Lock is currently held by: ${current_owner} (attempt ${attempt}/${max_attempts})"

        if [ $attempt -eq $max_attempts ]; then
            echo "ERROR: Timeout waiting for lock"
            return 1
        fi

        sleep 2
        ((attempt++))
    done
}

function check_lock() {
    local lock_contents=$(get_lock_contents)
    local current_owner

    current_owner=$(ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "cat '${LOCK_FILE}'" 2>/dev/null) || {
        echo "ERROR: Cannot read lock file"
        return 1
    }

    if [ "${current_owner}" != "${lock_contents}" ]; then
        echo "ERROR: Invalid lock state - it is held by ${current_owner}"
        return 1
    fi
}

function release_lock() {
    local lock_contents=$(get_lock_contents)
    local current_owner

    current_owner=$(ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "cat '${LOCK_FILE}'" 2>/dev/null) || {
        echo "ERROR: Cannot read lock file"
        return 1
    }

    if [ "${current_owner}" != "${lock_contents}" ]; then
        echo "ERROR: Cannot release lock - it is held by ${current_owner}"
        return 1
    fi

    if ! ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "rm -f '${LOCK_FILE}'"; then
        echo "ERROR: Failed to remove lock file"
        return 1
    fi
    echo "Lock released"
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
    check_lock || return 1
    ssh "${CONTROLLER_USERNAME}@${CONTROLLER_HOST}" "cd '${controller_path}' && uv run pytest $*"
    return $?
}

lock_obtained=false

check_ssh_connection || exit 1
verify_in_git_repo || exit 1

if obtain_lock; then
    lock_obtained=true
else
    exit 1
fi

copy_to_controller || exit 1

run_test "$@"
status=$?

exit $status
