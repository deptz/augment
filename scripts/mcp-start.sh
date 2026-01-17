#!/bin/bash
set -e

COMPOSE_FILE="docker-compose.mcp.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found"
    exit 1
fi

echo "Starting MCP servers..."
docker compose -f "$COMPOSE_FILE" up -d

echo "Waiting for services to be healthy..."
sleep 5

echo "MCP server status:"
docker compose -f "$COMPOSE_FILE" ps
