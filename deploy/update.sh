#!/bin/sh
# Pull-based deploy: the VM checks the registry itself, so GitHub needs no SSH
# access to the server. Run it from cron, for example every 5 minutes:
#   */5 * * * * /opt/taskmanager/update.sh >> /opt/taskmanager/update.log 2>&1
# Only containers whose image changed are recreated; the rest keep running.
set -eu
cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.prod.yml"
PROFILES=""
# start the AI worker as well once an AI key is configured
if grep -qE '^(NVIDIA|OPENAI)_API_KEY=..*' .env; then PROFILES="--profile ai"; fi

before=$($COMPOSE $PROFILES images -q 2>/dev/null | sort | tr '\n' ' ')
$COMPOSE $PROFILES pull -q
$COMPOSE $PROFILES up -d --remove-orphans
after=$($COMPOSE $PROFILES images -q 2>/dev/null | sort | tr '\n' ' ')

if [ "$before" != "$after" ]; then
    echo "$(date -Is) updated to new images"
    # remove only this project's old images, never other images on the server
    for repo in tm-portal-api tm-portal-ui tm-worker.notify; do
        docker image prune -f --filter "label=org.opencontainers.image.title=$repo" >/dev/null
    done
fi
