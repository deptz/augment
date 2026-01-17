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

**IMPORTANT**: MCP servers require **separate read-only credentials** with `MCP_` prefix. URLs are shared from main app configuration.

#### Credential Separation

MCP servers use **separate credentials** from the main application to enforce read-only access:

- **MCP Credentials** (required, `MCP_` prefix): Read-only username and API tokens for MCP servers
- **Shared Configuration** (no prefix): URLs and workspace configuration shared from main app

This separation ensures:
- **Security**: MCP servers can only read data, not modify
- **Principle of Least Privilege**: MCP credentials have minimal read-only scopes
- **Isolation**: Main app credentials (with write permissions) are not exposed to MCP containers

#### Required Variables

Add the following MCP credential variables to your `.env` file:

```bash
# ============================================================================
# Shared Configuration (used by both main app and MCP servers)
# ============================================================================
JIRA_SERVER_URL=https://your-company.atlassian.net
CONFLUENCE_SERVER_URL=https://your-company.atlassian.net/wiki
BITBUCKET_URL=https://api.bitbucket.org/2.0  # Optional, defaults to https://api.bitbucket.org/2.0

# Bitbucket Workspaces (for MCP server generation)
# For multiple workspaces, use comma-separated list:
BITBUCKET_WORKSPACES=workspace1,workspace2,workspace3
# OR for single workspace (backward compatible):
# BITBUCKET_WORKSPACE=your-workspace

# ============================================================================
# MCP Read-Only Credentials (REQUIRED - separate from main app credentials)
# ============================================================================
# These credentials MUST have READ-ONLY permissions/scopes

# JIRA Read-Only Credentials
MCP_JIRA_USERNAME=your.readonly.email@company.com
MCP_JIRA_API_TOKEN=your_readonly_jira_api_token

# Confluence Read-Only Credentials (Optional - defaults to JIRA credentials)
# MCP_CONFLUENCE_USERNAME=your.readonly.email@company.com  # Optional
# MCP_CONFLUENCE_API_TOKEN=your_readonly_confluence_api_token  # Optional

# Bitbucket Read-Only Credentials
MCP_BITBUCKET_EMAIL=your.readonly.email@company.com
MCP_BITBUCKET_API_TOKEN=your_readonly_bitbucket_app_password

# ============================================================================
# MCP Server Configuration (Optional)
# ============================================================================
MCP_NETWORK_NAME=augment-mcp-network  # Optional: defaults to augment-mcp-network
MCP_BITBUCKET_IMAGE=node:20-alpine  # Optional: defaults to node:20-alpine
MCP_ATLASSIAN_IMAGE=ghcr.io/sooperset/mcp-atlassian:latest  # Optional: defaults to ghcr.io/sooperset/mcp-atlassian:latest
```

**Important Notes**:
- **MCP Credentials are REQUIRED**: No fallback to main app credentials. If `MCP_*` variables are missing, MCP services will fail to start.
- **Read-Only Scopes**: MCP credentials must have read-only permissions:
  - **Jira**: Read-only access to issues, projects, boards (NO write, delete, or admin)
  - **Confluence**: Read-only access to pages, spaces (NO write, delete, or admin)
  - **Bitbucket**: Read-only access to repositories, PRs, commits (NO write, delete, or admin)
- **URLs are Shared**: `JIRA_SERVER_URL`, `CONFLUENCE_SERVER_URL`, and `BITBUCKET_URL` are shared from main app configuration (no `MCP_` prefix needed).
- **Multi-Workspace Support**: If `BITBUCKET_WORKSPACES` contains multiple workspaces (comma-separated), the system automatically creates one Bitbucket MCP instance per workspace:
  - Each instance gets a unique port (7001, 7002, 7003...) and hostname (`bitbucket-mcp-{workspace}`)
  - Example: `BITBUCKET_WORKSPACES=workspace1,workspace2,workspace3` creates 3 Bitbucket MCP instances
- **See `.env.example`**: For detailed documentation on creating read-only API tokens and required scopes.

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

## Agents.md Distribution

When OpenCode containers are spawned, the system automatically distributes an OpenCode-specific `Agents.md` file to guide agents on MCP usage:

1. **Automatic Distribution**: `Agents.md` files are created/updated in:
   - Each cloned repository root directory
   - Workspace root directory

2. **Smart Appending**: 
   - If a repository already has an `Agents.md` file, the OpenCode MCP integration section is appended (not overwritten)
   - Existing content is preserved with a clear separator (`---`)
   - Prevents duplicate content (idempotent - safe to run multiple times)

3. **Content**: The `Agents.md` file includes:
   - Available MCP servers (Bitbucket and Atlassian)
   - When to use each MCP (code vs documentation vs tickets)
   - Read-only constraints and safety rules
   - Best practices for data fetching (always fetch real data, minimize calls)
   - Reference to `/app/opencode.json` for MCP configuration

4. **Safety Features**:
   - Path sanitization prevents security issues
   - File size limits (10MB max for existing files)
   - Encoding error handling (UTF-8 with fallback)
   - Atomic file writes (prevents corruption)
   - Idempotency checks (prevents duplicate appends)

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
2. Verify MCP credential environment variables are set correctly:
   - Check for `MCP_JIRA_USERNAME`, `MCP_JIRA_API_TOKEN`, `MCP_BITBUCKET_EMAIL`, `MCP_BITBUCKET_API_TOKEN` in `.env`
3. Ensure MCP API tokens have **read-only** scopes and are valid
4. Verify shared URLs are set: `JIRA_SERVER_URL`, `CONFLUENCE_SERVER_URL` (no `MCP_` prefix needed)
5. Health checks use `wget` and may fall back to root endpoint (`/`) if `/health` doesn't exist
6. Verify containers are actually running: `docker compose -f docker-compose.mcp.yml ps`
7. If MCP credentials are missing, the compose generation will fail with clear error messages

### Environment Variable Issues

**IMPORTANT**: MCP servers use separate `MCP_*` prefixed credentials. URLs are shared from main app.

**Variable Mapping**:
- **URLs (shared)**: `JIRA_SERVER_URL` → mapped to `JIRA_URL` inside container
- **URLs (shared)**: `CONFLUENCE_SERVER_URL` → mapped to `CONFLUENCE_URL` inside container
- **Credentials (MCP only)**: `MCP_JIRA_USERNAME` → mapped to `JIRA_USERNAME` inside container
- **Credentials (MCP only)**: `MCP_JIRA_API_TOKEN` → mapped to `JIRA_API_TOKEN` inside container
- **Credentials (MCP only)**: `MCP_BITBUCKET_EMAIL` → mapped to `ATLASSIAN_USER_EMAIL` inside container
- **Credentials (MCP only)**: `MCP_BITBUCKET_API_TOKEN` → mapped to `ATLASSIAN_API_TOKEN` inside container

**Common mistakes**:
- **Missing `MCP_*` credentials**: MCP credentials are REQUIRED. No fallback to main app credentials. If missing, MCP services will fail to start with clear error messages.
- **Using main app credentials**: Do NOT use `JIRA_USERNAME`, `JIRA_API_TOKEN`, `BITBUCKET_EMAIL`, etc. for MCP. Use `MCP_*` prefixed variables instead.
- **Missing read-only scopes**: MCP credentials must have read-only permissions. Using write-enabled credentials is a security risk.
- **Not setting `BITBUCKET_WORKSPACES`**: When you have multiple workspaces, set `BITBUCKET_WORKSPACES` (comma-separated) to create multiple Bitbucket MCP instances.
- **Missing MCP credentials**: Ensure all required `MCP_*` variables are set in your `.env` file. See `.env.example` for the complete list.

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
