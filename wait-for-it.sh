#!/usr/bin/env bash
# wait-for-it.sh - Wait for service availability before starting application
# Adapted from https://github.com/vishnubob/wait-for-it

set -e

WAITFORIT_cmdname=${0##*/}
WAITFORIT_host=""
WAITFORIT_port=""
WAITFORIT_timeout=15
WAITFORIT_strict=0
WAITFORIT_child=0
WAITFORIT_quiet=0

usage() {
    cat << USAGE >&2
Usage:
    $WAITFORIT_cmdname host:port [-s] [-t timeout] [-- command args]
    -h HOST | --host=HOST       Host or IP under test
    -p PORT | --port=PORT       TCP port under test
    -s | --strict               Only execute subcommand if the test succeeds
    -q | --quiet                Don't output any status messages
    -t TIMEOUT | --timeout=TIMEOUT
                                Timeout in seconds, zero for no timeout
    -- COMMAND ARGS             Execute command with args after the test finishes
USAGE
    exit 1
}

wait_for() {
    if [[ $WAITFORIT_timeout -gt 0 ]]; then
        echo "🔨 Waiting $WAITFORIT_timeout seconds for $WAITFORIT_host:$WAITFORIT_port"
    else
        echo "🔨 Waiting for $WAITFORIT_host:$WAITFORIT_port without a timeout"
    fi
    
    WAITFORIT_start_ts=$(date +%s)
    while :
    do
        if [[ $WAITFORIT_host == "" || $WAITFORIT_port == "" ]]; then
            echo "❌ Error: you need to provide a host and port to test."
            usage
        fi
        
        nc -z "$WAITFORIT_host" "$WAITFORIT_port" >/dev/null 2>&1
        WAITFORIT_result=$?
        
        if [[ $WAITFORIT_result -eq 0 ]]; then
            echo "✅ $WAITFORIT_host:$WAITFORIT_port is available"
            break
        fi
        
        if [[ $WAITFORIT_timeout -gt 0 ]]; then
            WAITFORIT_end_ts=$(date +%s)
            WAITFORIT_elapsed=$(( WAITFORIT_end_ts - WAITFORIT_start_ts ))
            if [[ $WAITFORIT_elapsed -ge $WAITFORIT_timeout ]]; then
                echo "❌ Operation timed out" >&2
                exit 1
            fi
        fi
        
        sleep 1
    done
}

# Parse arguments
while [[ $# -gt 0 ]]
do
    case $1 in
        *:* )
        WAITFORIT_hostport=(${1//:/ })
        WAITFORIT_host=${WAITFORIT_hostport[0]}
        WAITFORIT_port=${WAITFORIT_hostport[1]}
        shift 1
        ;;
        --child)
        WAITFORIT_child=1
        shift 1
        ;;
        -q | --quiet)
        WAITFORIT_quiet=1
        shift 1
        ;;
        -s | --strict)
        WAITFORIT_strict=1
        shift 1
        ;;
        -h)
        WAITFORIT_host="$2"
        if [[ $WAITFORIT_host == "" ]]; then break; fi
        shift 2
        ;;
        --host=*)
        WAITFORIT_host="${1#*=}"
        shift 1
        ;;
        -p)
        WAITFORIT_port="$2"
        if [[ $WAITFORIT_port == "" ]]; then break; fi
        shift 2
        ;;
        --port=*)
        WAITFORIT_port="${1#*=}"
        shift 1
        ;;
        -t)
        WAITFORIT_timeout="$2"
        if [[ $WAITFORIT_timeout == "" ]]; then break; fi
        shift 2
        ;;
        --timeout=*)
        WAITFORIT_timeout="${1#*=}"
        shift 1
        ;;
        --)
        shift
        WAITFORIT_CLI=("$@")
        break
        ;;
        --help)
        usage
        ;;
        *)
        echo "Unknown argument: $1"
        usage
        ;;
    esac
done

if [[ "$WAITFORIT_host" == "" || "$WAITFORIT_port" == "" ]]; then
    echo "❌ Error: you need to provide a host and port to test."
    usage
fi

wait_for

if [[ $WAITFORIT_CLI != "" ]]; then
    echo "🚀 Starting application: ${WAITFORIT_CLI[*]}"
    exec "${WAITFORIT_CLI[@]}"
fi 