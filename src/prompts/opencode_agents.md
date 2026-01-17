# OpenCode MCP Integration

## Available MCP Servers

You have access to Model Context Protocol (MCP) servers that provide read-only access to external data sources. These servers are configured in `/app/opencode.json`.

### Bitbucket MCP

Provides access to Bitbucket repositories, files, pull requests, and commits.

**Use Bitbucket MCP when you need to:**
- Read repository files and directories
- Inspect pull request details, comments, and diffs
- Review commit history and changes
- Access branch information
- Read repository metadata

**Available via:** `bitbucket-{workspace}` MCP server (one per workspace)

### Atlassian MCP

Provides access to Jira issues and Confluence pages.

**Use Atlassian MCP when you need to:**
- Fetch Jira issue details, descriptions, comments, and status
- Read Confluence pages and documentation
- Access project and space information
- Retrieve linked issues and relationships

**Available via:** `atlassian` MCP server

## Important Rules

### Read-Only Access

⚠️ **These systems are READ-ONLY.**

- **Never** attempt to create, update, delete, merge, comment, or transition anything
- **Never** modify repository files, create branches, or open pull requests
- **Never** update Jira issues, create comments, or change status
- **Never** edit Confluence pages

All MCP servers are configured with read-only permissions. Any write operations will be rejected.

### Data Fetching Best Practices

1. **Always fetch real data first** - When a task references Jira issues, Confluence pages, or source code, use the MCP servers to fetch the actual data
2. **Do not hallucinate** - Never make up or assume field values that can be queried through MCP
3. **Minimize API calls** - Batch requests when possible, cache results when appropriate
4. **Verify before using** - Confirm data exists and is accessible before referencing it in your work

### When to Use Each MCP

- **For code-related tasks**: Use Bitbucket MCP to read files, PRs, and commits
- **For documentation tasks**: Use Atlassian MCP to read Confluence pages
- **For ticket/issue analysis**: Use Atlassian MCP to fetch Jira issue details
- **For cross-referencing**: Use both MCPs as needed, but always fetch real data

## Configuration

MCP servers are automatically configured based on the repositories being analyzed. Check `/app/opencode.json` for the exact MCP server URLs and capabilities available in this workspace.

## Call Limits

MCP calls are rate-limited to prevent excessive API usage. Be efficient with your requests and batch operations when possible.
