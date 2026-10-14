# Source this file from Bash or zsh; the child CLI keeps its existing arguments and permissions.
# zsh has no BASH_SOURCE: there ${(%):-%x} names the file being sourced.
SECOND_OPINION_COLLECTOR="$(CDPATH= cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" >/dev/null && pwd)/second_opinion_usage.py"
if [ ! -f "$SECOND_OPINION_COLLECTOR" ]; then
    printf 'capture.sh: collector not found at %s\n' "$SECOND_OPINION_COLLECTOR" >&2
    return 66
fi

second_opinion_run() (
    if [ "$#" -lt 4 ] || [ "$3" != -- ]; then
        printf 'Usage: second_opinion_run ROUTE MODEL -- COMMAND [ARG...]\n' >&2
        return 64
    fi
    command -v python3 >/dev/null || return 69
    umask 077
    so_route="$1"
    so_model="$2"
    shift 3
    so_output=$(mktemp -t second-opinion-output.XXXXXX) || return 73
    trap 'rm -f "$so_output"' EXIT
    so_run_id=$(python3 "$SECOND_OPINION_COLLECTOR" start --route "$so_route" --model "$so_model") || return 73
    if "$@" > "$so_output"; then
        so_child_exit=0
    else
        so_child_exit=$?
    fi
    if ! python3 "$SECOND_OPINION_COLLECTOR" finish --run-id "$so_run_id" --exit-code "$so_child_exit" < "$so_output" >&2; then
        printf 'USAGE_UNRECORDED run=%s; do not repeat the model call to repair telemetry.\n' "$so_run_id" >&2
    fi
    cat "$so_output"
    return "$so_child_exit"
)
