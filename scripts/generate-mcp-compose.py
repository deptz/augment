#!/usr/bin/env python3
"""
Generate docker-compose.mcp.yml dynamically based on configured workspaces.

This script reads BITBUCKET_WORKSPACES from configuration and generates
a docker-compose file with one Bitbucket MCP instance per workspace.
"""

import os
import sys
import re
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import Config


def validate_docker_image(image: str, default: str) -> str:
    """
    Validate and sanitize Docker image name.
    
    Args:
        image: Image value from environment variable
        default: Default value to use if image is empty or invalid
    
    Returns:
        Validated image string
    """
    # Strip whitespace
    image = image.strip() if image else ""
    
    # If empty, use default
    if not image:
        return default
    
    # Basic validation: Docker image names should not be empty and should contain at least one character
    # Allow common Docker image formats: registry/repo:tag, repo:tag, or just repo
    if len(image) == 0:
        return default
    
    # Return validated image (Docker Compose will handle further validation)
    return image


def validate_workspace_name(workspace: str) -> str:
    """
    Validate workspace name for use in Docker service/container names.
    
    Docker naming rules:
    - Must start with a letter or number
    - Can contain letters, numbers, underscores, and hyphens
    - Cannot contain special characters that break YAML or Docker
    
    Args:
        workspace: Workspace name to validate
    
    Returns:
        Sanitized workspace name
    """
    # Remove any characters that could break Docker naming or YAML
    # Allow: alphanumeric, hyphens, underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', workspace)
    
    # Ensure it starts with alphanumeric (Docker requirement)
    if sanitized and not sanitized[0].isalnum():
        sanitized = 'w' + sanitized
    
    # Remove consecutive hyphens/underscores
    sanitized = re.sub(r'[-_]{2,}', '-', sanitized)
    
    # Remove leading/trailing hyphens/underscores
    sanitized = sanitized.strip('-_')
    
    # If empty after sanitization, use a default
    if not sanitized:
        sanitized = 'workspace'
    
    return sanitized


def generate_bitbucket_mcp_service(workspace: str, index: int, base_port: int = 7001, image: str = "node:20-alpine", bitbucket_url: str = "https://api.bitbucket.org/2.0", port: int = None) -> str:
    """
    Generate a Bitbucket MCP service definition for a specific workspace.
    
    Args:
        workspace: Workspace name
        index: Zero-based index (for port calculation)
        base_port: Base port number (default 7001)
        image: Docker image to use (default: node:20-alpine)
        bitbucket_url: Bitbucket API URL (default: https://api.bitbucket.org/2.0)
        port: Port number to use (if None, calculated from base_port + index)
    
    Returns:
        YAML service definition as string
    """
    if port is None:
        port = base_port + index
    service_name = f"bitbucket-mcp-{workspace}"
    container_name = f"augment-{service_name}"
    hostname = service_name
    
    # Shell command to map MCP-specific credentials to MCP-expected names
    # Using @aashari/mcp-server-atlassian-bitbucket which supports HTTP/SSE transport
    # This package expects: ATLASSIAN_USER_EMAIL, ATLASSIAN_API_TOKEN, BITBUCKET_DEFAULT_WORKSPACE
    # MCP uses: MCP_BITBUCKET_EMAIL, MCP_BITBUCKET_API_TOKEN (read-only credentials)
    # Note: TRANSPORT_MODE=http enables HTTP/SSE server mode (listens on /mcp endpoint)
    # The node:20-alpine image already includes nodejs and npm, so we only need wget and git
    # Use list format for command to avoid YAML parsing issues with complex shell scripts
    # Use $$ to escape $ for Docker Compose variable interpolation
    command_content = f'''apk add --no-cache wget git 2>&1 || echo 'Packages may already be installed' &&
export ATLASSIAN_USER_EMAIL=\"$${{MCP_BITBUCKET_EMAIL}}\" &&
export ATLASSIAN_API_TOKEN=\"$${{MCP_BITBUCKET_API_TOKEN}}\" &&
export BITBUCKET_DEFAULT_WORKSPACE=\"$${{BITBUCKET_WORKSPACE}}\" &&
export PORT={port} &&
export TRANSPORT_MODE=http &&
echo \"Starting Bitbucket MCP server for workspace: $${{BITBUCKET_WORKSPACE}} on port {port}\" &&
echo \"Transport mode: http (SSE)\" &&
echo \"MCP endpoint: http://0.0.0.0:{port}/mcp\" &&
if [ -z \"$${{ATLASSIAN_USER_EMAIL}}\" ] || [ -z \"$${{ATLASSIAN_API_TOKEN}}\" ]; then
  echo \"ERROR: Missing MCP credentials. Required: MCP_BITBUCKET_EMAIL and MCP_BITBUCKET_API_TOKEN\" >&2
  exit 1
fi &&
echo \"Credentials configured for: $${{ATLASSIAN_USER_EMAIL}}\" &&
echo \"Launching MCP server...\" &&
exec npx -y @aashari/mcp-server-atlassian-bitbucket@latest 2>&1'''
    
    # Format command for YAML list format using literal block scalar
    command_lines = command_content.strip().split('\n')
    indented_command = '\n        '.join(command_lines)
    
    return f'''  {service_name}:
    image: {image}
    container_name: {container_name}
    working_dir: /app
    entrypoint: ["/bin/sh"]
    command:
      - -c
      - |
        {indented_command}
    ports:
      - "{port}:{port}"
    environment:
      - JIRA_SERVER_URL=${{JIRA_SERVER_URL}}
      - CONFLUENCE_SERVER_URL=${{CONFLUENCE_SERVER_URL}}
      - MCP_BITBUCKET_EMAIL=${{MCP_BITBUCKET_EMAIL}}
      - MCP_BITBUCKET_API_TOKEN=${{MCP_BITBUCKET_API_TOKEN}}
      - BITBUCKET_WORKSPACE={workspace}
      - BITBUCKET_URL={bitbucket_url}
      - PORT={port}
      - TRANSPORT_MODE=http
    networks:
      - augment-mcp
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:{port}/ 2>/dev/null || wget --no-verbose --tries=1 --spider http://localhost:{port}/mcp 2>/dev/null || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
'''


def generate_atlassian_mcp_service(bitbucket_services_count: int, base_port: int = 7001, image: str = "ghcr.io/sooperset/mcp-atlassian:latest", port: int = None) -> str:
    """
    Generate Atlassian MCP service definition.
    
    Args:
        bitbucket_services_count: Number of Bitbucket MCP services (to calculate port)
        base_port: Base port number (default 7001)
        image: Docker image to use (default: ghcr.io/sooperset/mcp-atlassian:latest)
        port: Port number to use (if None, calculated from bitbucket_services_count)
    
    Returns:
        YAML service definition as string
    """
    # Atlassian MCP uses port after all Bitbucket services
    # If only one workspace, use 7002. Otherwise use base_port + count
    if port is None:
        port = base_port + bitbucket_services_count if bitbucket_services_count > 1 else 7002
    
    # Shell command to map MCP-specific credentials to MCP-expected names
    # mcp-atlassian expects: JIRA_URL, CONFLUENCE_URL, JIRA_USERNAME, JIRA_API_TOKEN
    # URLs are shared: JIRA_SERVER_URL, CONFLUENCE_SERVER_URL
    # MCP uses: MCP_JIRA_USERNAME, MCP_JIRA_API_TOKEN (read-only credentials)
    # The Docker image should have mcp-atlassian pre-installed
    # Note: Using $$ to escape $ for Docker Compose interpolation
    # Note: Since entrypoint is /bin/sh, command should be -c "..." not sh -c "..."
    command = f'''-c "
        export JIRA_URL=\"$${{JIRA_SERVER_URL}}\" &&
        export CONFLUENCE_URL=\"$${{CONFLUENCE_SERVER_URL}}\" &&
        export JIRA_USERNAME=\"$${{MCP_JIRA_USERNAME}}\" &&
        export JIRA_API_TOKEN=\"$${{MCP_JIRA_API_TOKEN}}\" &&
        export CONFLUENCE_USERNAME=\"$${{MCP_CONFLUENCE_USERNAME:-$${{MCP_JIRA_USERNAME}}}}\" &&
        export CONFLUENCE_API_TOKEN=\"$${{MCP_CONFLUENCE_API_TOKEN:-$${{MCP_JIRA_API_TOKEN}}}}\" &&
        echo \"Starting Atlassian MCP server on port {port}\" &&
        echo \"JIRA_URL: $${{JIRA_URL}}\" &&
        echo \"CONFLUENCE_URL: $${{CONFLUENCE_URL}}\" &&
        if [ -z \"$${{JIRA_USERNAME}}\" ] || [ -z \"$${{JIRA_API_TOKEN}}\" ]; then
          echo \"ERROR: Missing MCP credentials. Required: MCP_JIRA_USERNAME and MCP_JIRA_API_TOKEN\" >&2
          exit 1
        fi &&
        (apk add --no-cache wget curl 2>/dev/null || (apt-get update && apt-get install -y wget curl) 2>/dev/null || true) &&
        if command -v mcp-atlassian >/dev/null 2>&1; then
          echo \"Found mcp-atlassian command, starting server...\" &&
          exec mcp-atlassian --transport streamable-http --port {port} --host 0.0.0.0
        elif command -v uvx >/dev/null 2>&1; then
          echo \"Found uvx, using it to run mcp-atlassian...\" &&
          exec uvx mcp-atlassian --transport streamable-http --port {port} --host 0.0.0.0
        elif python3 -m mcp_atlassian --help >/dev/null 2>&1; then
          echo \"Found python3 mcp_atlassian module, starting server...\" &&
          exec python3 -m mcp_atlassian --transport streamable-http --port {port} --host 0.0.0.0
        elif python -m mcp_atlassian --help >/dev/null 2>&1; then
          echo \"Found python mcp_atlassian module, starting server...\" &&
          exec python -m mcp_atlassian --transport streamable-http --port {port} --host 0.0.0.0
        else
          echo \"ERROR: Could not find mcp-atlassian command or module.\" &&
          echo \"Available in PATH: $$(echo $$PATH)\" &&
          echo \"Checking for commands:\" &&
          (command -v mcp-atlassian || echo \"  mcp-atlassian: not found\") &&
          (command -v uvx || echo \"  uvx: not found\") &&
          (command -v python3 || echo \"  python3: not found\") &&
          (command -v python || echo \"  python: not found\") &&
          echo \"The image may have a different entrypoint. Check image documentation.\" &&
          echo \"Container will exit with error.\" &&
          exit 1
        fi
      "'''
    
    # Format command for YAML list format using literal block scalar
    # This preserves the command structure and handles quotes properly
    # Remove the leading "-c " from the command since we add it as a separate list item
    command_content = command.strip()
    # Remove '-c "' from the start
    if command_content.startswith('-c "'):
        command_content = command_content[4:]  # Remove '-c "'
    elif command_content.startswith('-c'):
        # Handle case where there's a space after -c
        parts = command_content.split(' ', 1)
        if len(parts) > 1 and parts[1].startswith('"'):
            command_content = parts[1][1:]  # Remove the quote after space
        else:
            command_content = command_content[3:].lstrip()  # Remove '-c' and any following space
    
    # Remove trailing quote if present (but keep the content)
    if command_content.endswith('"'):
        command_content = command_content[:-1].rstrip()
    
    command_lines = command_content.split('\n')
    # Clean up each line (remove leading/trailing whitespace from the command content)
    cleaned_lines = [line.strip() for line in command_lines if line.strip()]
    # Indent each line for the YAML literal block
    indented_command = '\n        '.join(cleaned_lines)
    
    return f'''  atlassian-mcp:
    image: {image}
    container_name: augment-atlassian-mcp
    entrypoint: ["/bin/sh"]
    command:
      - -c
      - |
        {indented_command}
    ports:
      - "{port}:{port}"
    environment:
      - JIRA_SERVER_URL=${{JIRA_SERVER_URL}}
      - MCP_JIRA_USERNAME=${{MCP_JIRA_USERNAME}}
      - MCP_JIRA_API_TOKEN=${{MCP_JIRA_API_TOKEN}}
      - CONFLUENCE_SERVER_URL=${{CONFLUENCE_SERVER_URL}}
      - MCP_CONFLUENCE_USERNAME=${{MCP_CONFLUENCE_USERNAME:-${{MCP_JIRA_USERNAME}}}}
      - MCP_CONFLUENCE_API_TOKEN=${{MCP_CONFLUENCE_API_TOKEN:-${{MCP_JIRA_API_TOKEN}}}}
    networks:
      - augment-mcp
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:{port}/health 2>/dev/null || wget --no-verbose --tries=1 --spider http://localhost:{port}/ 2>/dev/null || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
'''


def validate_mcp_credentials() -> None:
    """
    Validate that required MCP credential environment variables are present.
    
    Raises:
        SystemExit: If required MCP credentials are missing
    """
    required_vars = [
        'MCP_JIRA_USERNAME',
        'MCP_JIRA_API_TOKEN',
        'MCP_BITBUCKET_EMAIL',
        'MCP_BITBUCKET_API_TOKEN',
    ]
    
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if not value or not value.strip():
            missing_vars.append(var)
    
    if missing_vars:
        print("ERROR: Missing required MCP credential environment variables:", file=sys.stderr)
        for var in missing_vars:
            print(f"  - {var}", file=sys.stderr)
        print("\nMCP servers require separate read-only credentials with MCP_ prefix.", file=sys.stderr)
        print("Set these variables in your .env file.", file=sys.stderr)
        print("See .env.example for required variables.", file=sys.stderr)
        sys.exit(1)


def generate_compose_file(output_path: str = "docker-compose.mcp.yml") -> None:
    """
    Generate docker-compose.mcp.yml file based on configured workspaces.
    
    Args:
        output_path: Path to output docker-compose file
    """
    # Validate MCP credentials are present (required, no fallback)
    validate_mcp_credentials()
    
    try:
        config = Config()
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Get workspaces from config
    workspaces = config.get_bitbucket_workspaces()
    
    # If no workspaces configured, use empty list (will create no Bitbucket MCP services)
    if not workspaces:
        print("Warning: No Bitbucket workspaces configured. Bitbucket MCP services will not be created.", file=sys.stderr)
        print("Set BITBUCKET_WORKSPACES or BITBUCKET_WORKSPACE in your .env file.", file=sys.stderr)
    
    # Get image values from environment with defaults (avoid Docker Compose interpolation issues)
    # Validate and sanitize to prevent empty values and YAML injection
    bitbucket_image_raw = os.getenv('MCP_BITBUCKET_IMAGE', '')
    atlassian_image_raw = os.getenv('MCP_ATLASSIAN_IMAGE', '')
    
    bitbucket_image = validate_docker_image(bitbucket_image_raw, 'node:20-alpine')
    atlassian_image = validate_docker_image(atlassian_image_raw, 'ghcr.io/sooperset/mcp-atlassian:latest')
    
    # Get network name from environment with default (avoid Docker Compose interpolation issues)
    network_name_raw = os.getenv('MCP_NETWORK_NAME', '')
    network_name = network_name_raw.strip() if network_name_raw else 'augment-mcp-network'
    if not network_name:
        network_name = 'augment-mcp-network'
    
    # Get Bitbucket URL from environment with default (avoid Docker Compose interpolation issues with colons in URLs)
    bitbucket_url_raw = os.getenv('BITBUCKET_URL', '')
    bitbucket_url = bitbucket_url_raw.strip() if bitbucket_url_raw else 'https://api.bitbucket.org/2.0'
    if not bitbucket_url:
        bitbucket_url = 'https://api.bitbucket.org/2.0'
    
    # Get port values from environment with defaults (avoid Docker Compose interpolation issues)
    # Note: Ports are calculated per service, but we can override via env vars if needed
    # For now, we'll use calculated ports directly (no env var override for ports)
    
    # Validate and sanitize workspace names for Docker naming safety
    workspaces = [validate_workspace_name(ws) for ws in workspaces]
    
    # Generate compose file content
    compose_content = f"""version: '3.8'

networks:
  augment-mcp:
    name: {network_name}
    driver: bridge

services:
"""
    
    # Generate Bitbucket MCP services (one per workspace)
    for index, workspace in enumerate(workspaces):
        compose_content += generate_bitbucket_mcp_service(workspace, index, image=bitbucket_image, bitbucket_url=bitbucket_url)
        compose_content += "\n"
    
    # Generate Atlassian MCP service
    compose_content += generate_atlassian_mcp_service(len(workspaces), image=atlassian_image)
    
    # Write to file
    output_file = Path(output_path)
    output_file.write_text(compose_content)
    
    print(f"Generated {output_path} with {len(workspaces)} Bitbucket MCP service(s) and 1 Atlassian MCP service")
    if workspaces:
        print(f"Workspaces: {', '.join(workspaces)}")
        for index, workspace in enumerate(workspaces):
            port = 7001 + index
            print(f"  - {workspace}: port {port}, hostname bitbucket-mcp-{workspace}")


if __name__ == "__main__":
    output_file = sys.argv[1] if len(sys.argv) > 1 else "docker-compose.mcp.yml"
    generate_compose_file(output_file)
