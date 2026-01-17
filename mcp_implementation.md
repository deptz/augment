## Implementation

```
You are implementing a headless OpenCode deployment with two self-hosted MCP servers:

1) Bitbucket MCP: https://github.com/MatanYemini/bitbucket-mcp  
2) Atlassian MCP (Jira + Confluence): https://github.com/sooperset/mcp-atlassian  

Goals:
- Run both MCP servers as independent Docker services.
- Authenticate both using API tokens (no OAuth).
- Expose MCP over HTTP.
- Configure OpenCode (headless) to connect to both MCP servers.
- Enforce READ-ONLY behavior end-to-end.
- Provide guardrails so agents cannot perform write actions.
- Add request logging and per-run call caps.

Deliverables:
1. docker-compose.yml with three services:
   - bitbucket-mcp
   - atlassian-mcp
   - opencode (headless)
2. Dockerfiles or run commands for both MCP servers.
3. opencode.json with MCP configuration for both servers.
4. A policy layer in OpenCode that:
   - Tags both MCPs as read-only
   - Blocks any tool whose name implies mutation (create/update/delete/merge/comment/transition)
   - Enforces a max call limit per run (e.g., 50)
5. AGENTS.md that instructs:
   - When to use Jira/Confluence vs Bitbucket
   - Never hallucinate when data can be fetched
   - Never attempt write operations

Constraints:
- No OAuth flows.
- Tokens via env vars.
- All services must run via docker compose.
- OpenCode runs in headless mode.
- MCP must be over HTTP.

Acceptance:
- OpenCode can fetch Jira issues, Confluence pages, and Bitbucket files/PRs/Commits.
- Logs show all MCP calls with timestamps and tool names.
- Restarting containers does not require re-auth.
```

---

## PRD — “Headless OpenCode with Self-Hosted MCP Fabric”

### Objective

Provide OpenCode (headless) with governed, read-only access to:

* Bitbucket repositories
* Jira issues
* Confluence pages

Using self-hosted MCP servers authenticated by tokens, not OAuth.

### Architecture

```
OpenCode (headless)
   |
   | MCP over HTTP
   |
+--------------------+        +--------------------+
| bitbucket-mcp      |        | atlassian-mcp      |
+--------------------+        +--------------------+
        |                               |
        | REST                          | REST
        |                               |
   Bitbucket API                 Jira / Confluence API
```

### Components

1. **bitbucket-mcp**

   * Source: MatanYemini/bitbucket-mcp
   * Auth: BITBUCKET_USERNAME + BITBUCKET_API_TOKEN
   * Mode: Read-only fork (remove write tools)

2. **atlassian-mcp**

   * Source: sooperset/mcp-atlassian
   * Auth: JIRA_USERNAME + JIRA_API_TOKEN
   * Mode: Read-only fork (remove write tools)

3. **OpenCode (headless)**

   * Loads MCP servers via `opencode.json`
   * Runs with a policy layer:

     * Blocks write tools
     * Enforces call caps
     * Logs all MCP calls

### Configuration

`opencode.json` (dynamically generated based on repos being analyzed)

**Single workspace:**
```json
{
  "mcp": {
    "bitbucket-workspace1": {
      "enabled": true,
      "url": "http://bitbucket-mcp-workspace1:7001/mcp",
      "read_only": true
    },
    "atlassian": {
      "enabled": true,
      "url": "http://atlassian-mcp:7002/mcp",
      "read_only": true
    }
  },
  "policy": {
    "max_calls_per_run": 50
  }
}
```

**Multiple workspaces:**
```json
{
  "mcp": {
    "bitbucket-workspace1": {
      "enabled": true,
      "url": "http://bitbucket-mcp-workspace1:7001/mcp",
      "read_only": true
    },
    "bitbucket-workspace2": {
      "enabled": true,
      "url": "http://bitbucket-mcp-workspace2:7002/mcp",
      "read_only": true
    },
    "atlassian": {
      "enabled": true,
      "url": "http://atlassian-mcp:7003/mcp",
      "read_only": true
    }
  },
  "policy": {
    "max_calls_per_run": 50
  }
}
```

Note: All workspaces always use `bitbucket-{workspace}` format in the `mcp` object, whether single or multiple workspaces are detected.

`AGENTS.md`

```
You have access to:
- Bitbucket MCP: for repositories, files, PRs.
- Atlassian MCP: for Jira issues and Confluence pages.

Rules:
- These systems are READ-ONLY.
- Never attempt to create, update, merge, comment, or transition anything.
- When a task references Jira, Confluence, or source code, fetch real data first.
- Do not hallucinate fields that can be queried.
- Minimize calls; batch when possible.
```

### Policy Layer

Implemented in OpenCode runtime:

* `WRITE_VERBS = ["create", "update", "delete", "merge", "comment", "transition", "close"]`
* On plan generation:

  * Reject any step referencing a write tool.
* On execution:

  * Hard cap MCP calls per run (default: 50).
  * Log every call:

    ```
    timestamp | server | tool | args_hash
    ```

### Non-Goals

* No write automation.
* No OAuth.
* No human-in-the-loop UI.

### Acceptance Criteria

* OpenCode can:

  * Fetch Jira issues by key.
  * Read Confluence pages.
  * Inspect Bitbucket repos and files.
* Any write attempt is blocked before reaching MCP.
* All MCP calls are logged.
* System runs fully via `docker compose up`.