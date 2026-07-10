#!/usr/bin/env bash
#
# Unified test runner for Mycelium E2E tests.
#
# Default mode (macOS-safe): runs suites directly via aetest.main()
# --easypy mode: runs easypy jobs inside the pyats-runner Docker container
#
# Usage:
#   ./run_tests.sh integration                         # quick local
#   ./run_tests.sh sanity --datafile data/local_datafile.yaml
#   ./run_tests.sh weekly_full --easypy                # full easypy in Docker
#   ./run_tests.sh core --easypy --datafile data/ci_datafile.yaml

set -euo pipefail

COMPOSE_FILE="infra/compose.e2e.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") <suite> [options]

Suites:
  integration     Cursor single-host adapter tests (75-77)
  sanity          Quick smoke test (rooms, memory, search, doctor)
  aio_cfn         All-in-one CFN negotiation: oc/he/cu cross-adapter on hub only
  core            Full core tests (rooms, memory, CLI, CFN, Matrix)
  convergence     Multi-agent simulated negotiation scenarios
  hub_and_spoke   Cross-device hub-and-spoke tests
  weekly_full     All test tiers (weekly long-running run)
  minimal         Minimal pyATS verification test

Options:
  --easypy          Run via easypy inside Docker (full reports, parallel tasks)
  --datafile FILE   Override the datafile (relative to project root)
  --testbed FILE    Override the testbed file (relative to project root)
  --build           Force rebuild of the pyats-runner image before running
  -h, --help        Show this help message

Examples:
  $(basename "$0") integration
  $(basename "$0") sanity --datafile data/local_datafile.yaml
  $(basename "$0") weekly_full --easypy
  $(basename "$0") core --easypy --datafile data/ci_datafile.yaml
EOF
    exit 0
}

resolve_suite_file() {
    local suite="$1"
    case "$suite" in
        minimal)  echo "suites/minimal_test.py" ;;
        aio_cfn)  echo "suites/aio_cfn_suite.py" ;;
        *)        echo "suites/${suite}_suite.py" ;;
    esac
}

resolve_job_file() {
    local suite="$1"
    case "$suite" in
        weekly_full) echo "jobs/weekly_e2e_job.py" ;;
        minimal)     echo "jobs/minimal_job.py" ;;
        aio_cfn)     echo "jobs/aio_cfn_job.py" ;;
        *)           echo "jobs/${suite}_job.py" ;;
    esac
}

resolve_default_datafile() {
    local suite="$1"
    case "$suite" in
        integration) echo "data/integration_datafile.yaml" ;;
        sanity)      echo "data/sanity_datafile.yaml" ;;
        aio_cfn)     echo "data/aio_cfn_datafile.yaml" ;;
        minimal)     echo "data/minimal_datafile.yaml" ;;
        core)        echo "data/core_datafile.yaml" ;;
        convergence) echo "data/convergence_datafile.yaml" ;;
        cursor)      echo "data/cursor_datafile.yaml" ;;
        hub_and_spoke) echo "data/distributed_datafile.yaml" ;;
        weekly_full) echo "data/weekly_datafile.yaml" ;;
        *)           echo "data/base_datafile.yaml" ;;
    esac
}

resolve_default_testbed() {
    local suite="$1"
    case "$suite" in
        aio_cfn)     echo "testbeds/aio.yaml" ;;
        hub_and_spoke|core|hermes*|scenarios) echo "testbeds/lab.yaml" ;;
        *)           echo "" ;;
    esac
}

[[ $# -eq 0 ]] && usage

SUITE=""
EASYPY=false
DATAFILE=""
TESTBED=""
BUILD=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --easypy)          EASYPY=true; shift ;;
        --datafile)        DATAFILE="$2"; shift 2 ;;
        --testbed)         TESTBED="$2"; shift 2 ;;
        --build)           BUILD=true; shift ;;
        -h|--help)         usage ;;
        -*)                echo "Unknown option: $1" >&2; exit 1 ;;
        *)
            if [[ -z "$SUITE" ]]; then
                SUITE="$1"
            else
                echo "Unexpected argument: $1" >&2; exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$SUITE" ]]; then
    echo "Error: suite name is required" >&2
    usage
fi

SUITE_FILE="$(resolve_suite_file "$SUITE")"
JOB_FILE="$(resolve_job_file "$SUITE")"
DATAFILE="${DATAFILE:-$(resolve_default_datafile "$SUITE")}"
TESTBED="${TESTBED:-$(resolve_default_testbed "$SUITE")}"

cd "$SCRIPT_DIR"

if [[ ! -f "$SUITE_FILE" ]]; then
    echo "Error: suite file not found: $SUITE_FILE" >&2
    exit 1
fi

if $EASYPY; then
    if [[ ! -f "$JOB_FILE" ]]; then
        echo "Error: job file not found: $JOB_FILE" >&2
        exit 1
    fi

    if $BUILD; then
        echo "Building pyats-runner image..."
        docker compose -f "$COMPOSE_FILE" build pyats-runner
    fi

    echo "Running via easypy in Docker: $JOB_FILE (datafile: $DATAFILE)"
    docker compose -f "$COMPOSE_FILE" run --rm pyats-runner \
        pyats run job "$JOB_FILE" --datafile "$DATAFILE"
else
    TESTBED_ARGS=()
    if [[ -n "$TESTBED" && -f "$TESTBED" ]]; then
        TESTBED_ARGS=(--testbed-file "$TESTBED")
        echo "Running via aetest.main(): $SUITE_FILE (datafile: $DATAFILE, testbed: $TESTBED)"
    else
        echo "Running via aetest.main(): $SUITE_FILE (datafile: $DATAFILE)"
    fi
    uv run python "$SUITE_FILE" --datafile "$DATAFILE" "${TESTBED_ARGS[@]}"
fi
