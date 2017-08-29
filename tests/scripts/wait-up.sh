#!/usr/bin/env bash
set -e

if [ $# -lt 1 ]; then
    printf "First parameter URL required.\n"
    exit 1
fi

COUNTER=0
STEP_SIZE=1
MAX_SECONDS=${2:-10} # Wait 10 seconds if parameter not provided
MAX_RETRIES=$(( $MAX_SECONDS / $STEP_SIZE))

URL=$1

printf "Waiting URL: "$URL"\n"

until $(curl --insecure --output /dev/null --silent --fail $URL) || [ $COUNTER -eq $MAX_RETRIES ]; do
    printf '.'
    sleep $STEP_SIZE
    COUNTER=$(($COUNTER + 1))
done
if [ $COUNTER -eq $MAX_RETRIES ]; then
    printf "\nTimeout after "$(( $COUNTER * $STEP_SIZE))" second(s).\n"
    exit 2
else
    printf "\nUp successfully after "$(( $COUNTER * $STEP_SIZE))" second(s).\n"
fi