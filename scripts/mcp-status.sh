#!/bin/bash

COMPOSE_FILE="docker-compose.mcp.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found"
    exit 1
fi

docker compose -f "$COMPOSE_FILE" ps
