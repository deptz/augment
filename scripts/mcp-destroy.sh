#!/bin/bash
set -e

COMPOSE_FILE="docker-compose.mcp.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Error: $COMPOSE_FILE not found"
    exit 1
fi

read -p "Are you sure you want to destroy MCP servers and remove volumes? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled"
    exit 1
fi

echo "Destroying MCP servers..."
docker compose -f "$COMPOSE_FILE" down -v

echo "MCP servers destroyed"
