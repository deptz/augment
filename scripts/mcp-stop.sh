#!/bin/bash
set -e

COMPOSE_FILE="docker-compose.mcp.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found"
    exit 1
fi

echo "Stopping MCP servers..."
docker compose -f "$COMPOSE_FILE" stop

echo "MCP servers stopped"
