#!/usr/bin/env bash
#
# Mycelium E2E test runner (SLIM-native).
#
# Usage:
#   ./run_tests.sh pr           # Tier A — stack health, memory, protocol
#   ./run_tests.sh nightly      # Tier A + B — includes stub coordination
#   ./run_tests.sh canary       # Tier C — live agent canary (informational)
#
# Options:
#   --datafile FILE   Override datafile (relative to data/)
#   --testbed FILE    Override testbed (default: testbeds/local.yaml)
#   --lab             Use testbeds/lab.yaml (for running against oclw4)
#   -h, --help        Show this help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") <suite> [options]

Suites:
  pr        Tier A — stack health, memory, protocol (~10 min, no LLM)
  nightly   Tier A + B — includes stub coordination (~30 min, no LLM)
  canary    Tier C — live agent multi-episode (informational only, needs LLM)

Options:
  --datafile FILE   Datafile path (relative to project root or data/)
  --testbed FILE    Testbed YAML path (default: testbeds/local.yaml)
  --lab             Shorthand for --testbed testbeds/lab.yaml
  -h, --help        Show this message

Examples:
  ./run_tests.sh pr
  ./run_tests.sh nightly --lab
  ./run_tests.sh canary --datafile data/canary_datafile.yaml
  MYCELIUM_BACKEND_URL=http://10.0.50.125:8000 ./run_tests.sh pr --lab
EOF
    exit 0
}

resolve_job() {
    case "$1" in
        pr)      echo "jobs/pr_job.py" ;;
        nightly) echo "jobs/nightly_job.py" ;;
        canary)  echo "jobs/canary_job.py" ;;
        *)       echo "jobs/${1}_job.py" ;;
    esac
}

resolve_datafile() {
    case "$1" in
        pr)      echo "data/pr_datafile.yaml" ;;
        nightly) echo "data/nightly_datafile.yaml" ;;
        canary)  echo "data/canary_datafile.yaml" ;;
        *)       echo "data/base_datafile.yaml" ;;
    esac
}

[[ $# -eq 0 ]] && usage

SUITE=""
DATAFILE=""
TESTBED="testbeds/local.yaml"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --datafile) DATAFILE="$2"; shift 2 ;;
        --testbed)  TESTBED="$2"; shift 2 ;;
        --lab)      TESTBED="testbeds/lab.yaml"; shift ;;
        -h|--help)  usage ;;
        -*)         echo "Unknown option: $1" >&2; exit 1 ;;
        *)
            [[ -z "$SUITE" ]] && SUITE="$1" || { echo "Unexpected argument: $1" >&2; exit 1; }
            shift
            ;;
    esac
done

[[ -z "$SUITE" ]] && { echo "Error: suite name required" >&2; usage; }

JOB_FILE="$(resolve_job "$SUITE")"
DATAFILE="${DATAFILE:-$(resolve_datafile "$SUITE")}"

# Allow bare filenames for datafile (resolve against data/)
if [[ -n "$DATAFILE" && ! -f "$DATAFILE" && -f "data/$DATAFILE" ]]; then
    DATAFILE="data/$DATAFILE"
fi

cd "$SCRIPT_DIR"

if [[ ! -f "$JOB_FILE" ]]; then
    echo "Error: job file not found: $JOB_FILE" >&2; exit 1
fi

echo "Suite:    $SUITE"
echo "Job:      $JOB_FILE"
echo "Datafile: $DATAFILE"
echo "Testbed:  $TESTBED"
echo ""

uv run pyats run job "$JOB_FILE" \
    --testbed-file "$TESTBED" \
    --datafile "$DATAFILE"
