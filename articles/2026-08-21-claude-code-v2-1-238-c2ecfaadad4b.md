---
title: "Claude Code v2.1.238"
date: 2026-08-21
source: Claude Code Releases
source_url: https://github.com/anthropics/claude-code/releases/tag/v2.1.238
---

# Claude Code v2.1.238

<h2>What's changed</h2>
<ul>
<li>Added a <code>keybindingFlavor</code> setting: set it to <code>"readline"</code> to make Ctrl+W in the prompt delete back to the previous whitespace, as in Bash; the default (<code>"classic"</code>) is unchanged</li>
<li>Plugin marketplaces: <code>headersHelper</code> on a url marketplace or a catalog entry runs a command that mints HTTP headers (e.g. a short-lived token) for catalog and same-origin archive fetches</li>
<li>A catalog entry's <code>headersHelper</code> runs only when you install or update that plugin, after its command is shown; <code>claude plugin install/update</code> ask <code>[y/N]</code> (or pass <code>-y</code>)</li>
<li>Added <code>claude self-hosted-runner --defer-shutdown-max-min &lt;minutes&gt;</code>: on SIGTERM, keep serving attached sessions, park what is left after that many minutes, then exit</li>
<li>Added <code>claude self-hosted-runner --proxy-authorization-command</code> / <code>--proxy-authorization-file</code> for egress proxies that require a freshly issued <code>Proxy-Authorization</code> header on every connection</li>
<li>Fixed unbounded memory growth in long interactive sessions: subagent tool results are now released once they leave the recent display window</li>
<li>Fixed custom, project, and plugin output styles drifting back to the default voice mid-session</li>
<li>Fixed <code>CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION=true</code> not keeping prompt suggestions on when your account is near, but not over, its usage limit</li>
<li>Fixed worktree-isolation Bash refusals telling you to remove a redirect when the command had none</li>
<li>Fixed self-hosted runners occasionally being removed by the server after a single slow or lost poll request, handing their healthy session to another runner</li>
<li>Fixed MCP elicitation dialogs showing nothing for URLs longer than 4,096 characters, and permission prompts dropping the "don't ask again" option when the project path didn't fit the terminal width</li>
<li>Fixed leftover <code>/tmp/claude-*-cwd</code> files when a Bash command is killed, times out, or is interrupted</li>
<li>Fixed held Backspace being ignored on terminals that send Ctrl+H for Backspace when keystrokes arrive in large bursts (slow SSH/mosh links)</li>
<li>Fixed text-wrapping in permission prompt diffs: lines containing wide multi-code-point characters (such as emoji) or tabs are no longer clipped</li>
<li>Fixed killing a suspended (Ctrl+Z) session sometimes leaving the terminal in bracketed-paste mode with the cursor hidden</li>
<li>Fixed stdio MCP servers receiving a <code>server/discover</code> request before <code>initialize</code>, forcing lazy servers to start their backend on every session open</li>
<li>Fixed a proxy's refusal of a connection being reported as a generic network error instead of naming the proxy</li>
<li>Fixed the <code>/model</code> and <code>/effort</code> cache-miss warning appearing when the prompt cache had already expired</li>
<li>Fixed per-task Stop from the Remote Control tasks panel doing nothing on CLI-hosted sessions</li>
<li>Fixed remote sessions exiting when a client delivered a user message without a valid role</li>
<li>Fixed Remote Control sessions started by <code>claude remote-control</code> inheriting session-scoped environment variables from the launching shell</li>
<li>Fixed a Remote Control session whose process crashed staying unavailable until <code>claude remote-control</code> was restarted; it can now be reused when you next message it</li>
<li>Fixed Remote Control messages sent from the web or Desktop while Claude is mid-turn disappearing from the transcript after the turn finishes</li>
<li>Fixed Remote Control model picks made on a phone or web not updating the model shown in the terminal</li>
<li>Fixed Remote Control disconnecting with "login expired" when a brief network hiccup delays renewing your sign-in; it now retries and stays connected</li>
<li>Fixed Remote Control reporting a failed reconnect on sign-out; signing out now ends the session with a clear message</li>
<li>Fixed <code>ListAgents</code>/<code>SendMessage</code> reporting "Remote Control is not connected" in sessions run by <code>claude remote-control</code> (server mode) or Desktop/IDE hosts; they now list and reach Remote Control peers</li>
<li>Fixed <code>ListAgents</code> and <code>SendMessage</code> exposing the idle worker that the agent view pre-warms for your next background session; it now appears only once a task claims it</li>
<li>Cross-session messaging: sending to a session on this machine that refuses inbound messages (e.g. <code>crossSessionInbound: "refuse"</code>) now reports "refused" to the sender instead of a silent success</li>
<li>Cross-session messaging: a session whose inbox drops your messages (rate limit or full queue) now tells your session, instead of the messages vanishing silently</li>
<li>Improved startup: bare <code>claude</code> starts sooner on macOS</li>
<li>Improved Bash tool permission checking for zsh-specific syntax in shell conditionals</li>
<li>Improved Remote Control connection resilience: brief HTTP 403 refusals from a network edge, VPN, or proxy are now tolerated for up to 3 minutes, with the refusing party named when a block persists</li>
<li>Improved startup responsiveness: the automatic update check now runs about 10 seconds after launch instead of competing with startup for CPU</li>
<li>Updated the bundled <code>claude-api</code> skill for the Managed Agents Aug 19 release: web search/fetch domain settings and memory stores on self-hosted sandboxes</li>
<li>Changed Ctrl+L and Cmd+K in fullscreen to always just repaint — the double-press <code>/clear</code> shortcut was removed, and 1-row nvim terminals no longer trigger automatic <code>/clear</code> loops</li>
<li>Changed <code>claude mcp list</code> and <code>claude mcp get</code> to show disabled servers as <code>⊘ Disabled</code> instead of connecting to them for a health check</li>
<li>MCP <code>headersHelper</code> in a project <code>.mcp.json</code>, and inline MCP servers in project or <code>--add-dir</code> agent files, now require that folder's trust dialog to have been accepted (also under <code>claude -p</code>)</li>
<li>MCP <code>headersHelper</code> from a project <code>.mcp.json</code>, plugin, or agent file runs without inherited credential env vars; user, managed and claude.ai-scope helpers now run from the Claude config dir</li>
</ul>

This story surfaced via Claude Code Releases. For the original details and any numbers we have not confirmed here, follow the source below.

## Sources

- [Claude Code Releases](https://github.com/anthropics/claude-code/releases/tag/v2.1.238)

