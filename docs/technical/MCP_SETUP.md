# MCP Server Setup

MCP (Model Context Protocol) servers provide read-only access to external data sources (Bitbucket repositories, Jira issues, and Confluence pages) for OpenCode containers. MCP servers run as persistent services separate from OpenCode containers, which spawn dynamically on-demand.

> **📊 Architecture Diagrams**: For detailed visual architecture diagrams, see [MCP Architecture](MCP_ARCHITECTURE.md).

## Architecture

- **MCP Servers**: Persistent services running via `docker-compose.mcp.yml` (dynamically generated)
  - **Bitbucket MCP**: One instance per workspace (automatically created based on `BITBUCKET_WORKSPACES`)
    - All instances use format: `bitbucket-mcp-{workspace}` (e.g., `bitbucket-mcp-workspace1`)
    - Ports: 7001, 7002, 7003... (one per workspace, sequential)
    - Provides access to Bitbucket repositories, files, PRs, and commits
  - **Atlassian MCP**: Single instance providing access to Jira issues and Confluence pages
    - Port: 7002 (or next available after Bitbucket MCP instances)
- **OpenCode Containers**: Spawned dynamically when needed, automatically connect to MCP network
  - Each container gets a dynamically generated `opencode.json` with appropriate MCP URLs based on repos being analyzed
- **Docker Network**: `augment-mcp-network` enables communication between OpenCode containers and MCP servers

## Prerequisites

- Docker and Docker Compose installed
- API tokens with read-only scopes for:
  - Bitbucket (App Password)
  - Jira (API Token)
  - Confluence (API Token - same as Jira)

## Configuration

### Environment Variables

**IMPORTANT**: MCP servers use the **SAME environment variables as the main application**. No duplicate variables needed!

Add the following to your `.env` file:

```bash
# Main Application Configuration (REQUIRED - used by both main app and MCP servers)
JIRA_SERVER_URL=https://your-company.atlassian.net
JIRA_USERNAME=your.email@company.com
JIRA_API_TOKEN=your_jira_api_token
CONFLUENCE_SERVER_URL=https://your-company.atlassian.net/wiki
CONFLUENCE_USERNAME=your.email@company.com  # Optional: defaults to JIRA_USERNAME if not set
CONFLUENCE_API_TOKEN=your_confluence_api_token  # Optional: defaults to JIRA_API_TOKEN if not set

# Bitbucket Configuration (REQUIRED for Bitbucket MCP)
# For multiple workspaces, use comma-separated list:
BITBUCKET_WORKSPACES=workspace1,workspace2,workspace3
# OR for single workspace (backward compatible):
# BITBUCKET_WORKSPACE=your-workspace
BITBUCKET_EMAIL=your-email@company.com
BITBUCKET_API_TOKEN=your_bitbucket_app_password

# MCP Docker Network
MCP_NETWORK_NAME=augment-mcp-network

# MCP Server Configuration
MCP_BITBUCKET_ENABLED=true
MCP_ATLASSIAN_ENABLED=true
MCP_MAX_CALLS=50

# Optional: MCP Server Image Overrides
MCP_BITBUCKET_IMAGE=node:20-alpine  # Optional: defaults to node:20-alpine
MCP_ATLASSIAN_IMAGE=ghcr.io/sooperset/mcp-atlassian:latest  # Optional: defaults to ghcr.io/sooperset/mcp-atlassian:latest
```

**Important Notes**:
- **Unified Variables**: MCP servers automatically use `JIRA_SERVER_URL`, `CONFLUENCE_SERVER_URL`, and `BITBUCKET_EMAIL` from your main app configuration. No need to set `JIRA_URL`, `CONFLUENCE_URL`, or `BITBUCKET_USERNAME` separately.
- **Multi-Workspace Support**: If `BITBUCKET_WORKSPACES` contains multiple workspaces (comma-separated), the system automatically creates one Bitbucket MCP instance per workspace:
  - Each instance gets a unique port (7001, 7002, 7003...) and hostname (`bitbucket-mcp-{workspace}`)
  - Example: `BITBUCKET_WORKSPACES=workspace1,workspace2,workspace3` creates 3 Bitbucket MCP instances
- Ensure your API tokens (`BITBUCKET_API_TOKEN`, `JIRA_API_TOKEN`) have read-only scopes to restrict write operations at the API level.
- Image variables (`MCP_BITBUCKET_IMAGE`, `MCP_ATLASSIAN_IMAGE`) are optional and have defaults.

## Starting MCP Servers

### Using CLI

```bash
python main.py mcp start
```

### Using Shell Script

```bash
./scripts/mcp-start.sh
```

This will:
1. **Generate `docker-compose.mcp.yml` dynamically** based on `BITBUCKET_WORKSPACES` configuration
2. Create one Bitbucket MCP instance per workspace (if multiple workspaces configured)
3. Start all MCP servers in detached mode
4. Create the `augment-mcp-network` Docker network
5. Wait for services to be healthy
6. Display service status

## Stopping MCP Servers

### Using CLI

```bash
python main.py mcp stop
```

### Using Shell Script

```bash
./scripts/mcp-stop.sh
```

This stops the MCP servers but keeps them and the network available for quick restart.

## Checking Status

### Using CLI

```bash
python main.py mcp status
```

### Using Shell Script

```bash
./scripts/mcp-status.sh
```

Shows the current status of MCP services (running, stopped, health status).

## Destroying MCP Servers

### Using CLI

```bash
python main.py mcp destroy
```

### Using Shell Script

```bash
./scripts/mcp-destroy.sh
```

This will:
1. Stop all MCP services
2. Remove containers
3. Remove the Docker network
4. Remove volumes (if any)

**Warning**: This permanently removes MCP servers and network. You'll need to run `mcp start` again to recreate them.

## Integration with OpenCode

When OpenCode containers are spawned (via API endpoints with `repos` parameter), they automatically:

1. Connect to the `augment-mcp-network` if it exists
2. **Generate `opencode.json` dynamically** based on the repos being analyzed:
   - Extracts workspace information from repository URLs
   - Includes appropriate Bitbucket MCP URLs (one per workspace found in repos)
   - Each workspace gets its own key in the `mcp` object: `bitbucket-{workspace}` (always used for single or multiple workspaces)
   - Includes Atlassian MCP URL
   - Mounts the generated file into the container
3. Can access MCP servers via Docker network hostnames:
   - Bitbucket MCP: `http://bitbucket-mcp-{workspace}:{port}/mcp` (port depends on workspace index)
   - Atlassian MCP: `http://atlassian-mcp:{port}/mcp` (port is 7002 or next available after Bitbucket instances)

**Example - Single workspace**: If analyzing repos from `workspace1`:
- Container gets `opencode.json` with `bitbucket-workspace1` key:
  ```json
  {
    "mcp": {
      "bitbucket-workspace1": {
        "url": "http://bitbucket-mcp-workspace1:7001/mcp",
        "enabled": true,
        "read_only": true
      },
      "atlassian": {
        "url": "http://atlassian-mcp:7002/mcp",
        "enabled": true,
        "read_only": true
      }
    }
  }
  ```

**Example - Multiple workspaces**: If analyzing repos from `workspace1` and `workspace2`:
- Container gets `opencode.json` with separate keys for each workspace:
  ```json
  {
    "mcp": {
      "bitbucket-workspace1": {
        "url": "http://bitbucket-mcp-workspace1:7001/mcp",
        "enabled": true,
        "read_only": true
      },
      "bitbucket-workspace2": {
        "url": "http://bitbucket-mcp-workspace2:7002/mcp",
        "enabled": true,
        "read_only": true
      },
      "atlassian": {
        "url": "http://atlassian-mcp:7003/mcp",
        "enabled": true,
        "read_only": true
      }
    }
  }
  ```
- Can access `http://bitbucket-mcp-workspace1:7001/mcp` and `http://bitbucket-mcp-workspace2:7002/mcp`

If the MCP network doesn't exist when OpenCode containers are spawned, a warning is logged but the container will still start (without MCP access).

## Troubleshooting

### MCP Network Not Found

If you see warnings about the MCP network not being found:

1. Check if MCP servers are running: `python main.py mcp status`
2. If not running, start them: `python main.py mcp start`
3. Verify network exists: `docker network ls | grep augment-mcp-network`

### OpenCode Containers Can't Reach MCP Servers

1. Verify MCP servers are healthy: `docker compose -f docker-compose.mcp.yml ps`
2. Check network connectivity: `docker network inspect augment-mcp-network`
3. Verify OpenCode containers are on the network: `docker inspect <container-id> | grep NetworkMode`

### Health Check Failures

If MCP server health checks are failing:

1. Check container logs: `docker compose -f docker-compose.mcp.yml logs`
2. Verify environment variables are set correctly in `.env`
3. Ensure API tokens have correct scopes and are valid
4. Health checks use `wget` and may fall back to root endpoint (`/`) if `/health` doesn't exist
5. Verify containers are actually running: `docker compose -f docker-compose.mcp.yml ps`

### Environment Variable Issues

**IMPORTANT**: MCP servers now use the same variable names as the main application. The system automatically maps them internally.

**Variable Mapping**:
- Main app uses: `JIRA_SERVER_URL` → MCP servers use: `JIRA_URL` (mapped automatically)
- Main app uses: `CONFLUENCE_SERVER_URL` → MCP servers use: `CONFLUENCE_URL` (mapped automatically)
- Main app uses: `BITBUCKET_EMAIL` → MCP servers use: `BITBUCKET_USERNAME` (mapped automatically)

**Common mistakes**:
- Setting duplicate variables (`JIRA_URL`, `CONFLUENCE_URL`, `BITBUCKET_USERNAME`) - **Not needed!** Use main app variables instead.
- Missing `CONFLUENCE_USERNAME` or `CONFLUENCE_API_TOKEN` - these default to Jira values if not set
- Not setting `BITBUCKET_WORKSPACES` when you have multiple workspaces - this prevents multi-instance creation

### Container Startup Issues

If containers fail to start:

1. **Atlassian MCP**: The container tries multiple methods to run `mcp-atlassian` (direct command, `uvx`, or Python module). Check logs to see which method is being used.
2. **Bitbucket MCP**: Requires Node.js and installs the package via `npx`. Ensure the npm package `@matanyemini/bitbucket-mcp` is accessible.
3. **Network issues**: Verify the `augment-mcp-network` is created: `docker network ls | grep augment-mcp-network`
4. **Port conflicts**: Ensure ports 7001, 7002, 7003... (depending on number of workspaces) are not already in use. Each Bitbucket MCP instance uses a sequential port starting from 7001.
5. **Multiple workspaces not working**: Verify `BITBUCKET_WORKSPACES` is set correctly (comma-separated, no spaces). Check generated `docker-compose.mcp.yml` to see if multiple instances were created.

## Next Steps

After MCP servers are running, you can use OpenCode with MCP access by:

1. Including the `repos` parameter in API requests (generation, planning, story analysis)
2. OpenCode containers will automatically connect to MCP servers
3. The LLM inside OpenCode can fetch real data from Bitbucket, Jira, and Confluence via MCP

See the main [README.md](../README.md) for API usage examples.
