# AI access through MCP

The MCP adapter gives AI clients access to the same local application services used by the cockpit. It does not place live orders, connect to a broker, or change `execution_allowed`; paper actions remain subject to the application gates and confirmation tokens.

## Local clients

Use stdio for a client running on the machine that holds the configured data root. The repository's `.mcp.json.example` shows the local launcher setup. Keep the process root pointed at the one configured data root and leave its launch tiers at `read` unless a workflow needs more access.

Claude Code can also connect to a Streamable HTTP endpoint with `claude mcp add --transport http etf-cockpit <HTTPS-MCP-endpoint>`. Codex supports remote MCP servers configured in its MCP settings or with `codex mcp add`; use the HTTPS endpoint and OAuth login provided by the configured identity provider. For local-only access, prefer the stdio configuration.

## Remote Streamable HTTP

Remote access is disabled in `configs/mcp_v1.yaml`. To enable it, configure an OAuth 2.1 identity provider and set `remote.enabled` to `true`. Set `ETF_COCKPIT_MCP_ISSUER_URL` and `ETF_COCKPIT_MCP_RESOURCE_URL` to the provider issuer and the exact public MCP resource URL. Both must use HTTPS. Start the HTTP adapter from a host application that supplies the provider's verified `TokenVerifier` to `create_http_server` or `run_http_server` in `etf_cockpit.mcp.http`.

The adapter is an OAuth resource server: it verifies bearer tokens on every request and does not issue tokens or implement a login page. The verified token's `client_id` is used for audit and confirmation binding. Only the `core` profile is exposed remotely. `cockpit:read`, `cockpit:research`, and `cockpit:paper` each grant only their corresponding tier; an OAuth client that needs more than one tier must be issued every corresponding scope. Edit, ticket, fill, file-path, and live broker access are not available remotely.

When connecting ChatGPT, use the account or workspace's custom MCP app configuration or its supported Secure MCP Tunnel flow. ChatGPT's published connector features and available setup surfaces depend on the account or workspace; confirm the live UX during deployment. Choose OAuth when the provider supports it. Review write-tool approvals before sharing the app, and keep only the required scopes enabled.

The HTTP server binds to `127.0.0.1:8000` at `/mcp` by default. Keep it on loopback behind the selected HTTPS ingress or tunnel. The ingress must preserve the configured resource host so the SDK's DNS-rebinding check can validate it. Do not expose the MCP process directly to the public network.

## Tunnel lifetime

The helper `scripts/mcp_tunnel.ps1` is disabled unless called with `-Enabled`. Supply the tunnel executable and its arguments explicitly. It stops the process it started after at most 30 minutes by default; `-MaxDurationMinutes` can be set from 1 to 120. Keep the MCP service and tunnel closed when they are not in use. The helper does not install or configure a tunnel provider.

## Output and safety

MCP results use the standard envelope and existing tool paging. Most list tools default to 25 rows and cap a page at 100 rows; continue with the returned cursor. Missing evidence remains unavailable and is never replaced with zero. Research and paper writes require a fresh valid confirmation token, and all remote calls use the normal MCP audit and rate-limit checks. An OAuth scope does not bypass risk, data-quality, authority, or confirmation gates.

The MCP SDK publishes OAuth protected-resource metadata for compatible clients. See the [MCP Python SDK authorization guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md), [Claude Code MCP documentation](https://docs.anthropic.com/en/docs/claude-code/mcp), [Codex MCP documentation](https://developers.openai.com/codex/mcp), and [ChatGPT custom MCP server setup](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) for client-specific setup and current availability.
