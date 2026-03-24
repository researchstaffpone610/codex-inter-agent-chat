---
name: inter-agent-chat-codex
description: Use when multiple independent Codex terminal sessions need to send messages to each other, broadcast to all registered agents, or interpret injected messages prefixed with [@agentName]. Covers Codex SessionStart terminal registration, direct codex-team messaging, tmux-first transport, and TIOCSTI fallback.
hooks:
  SessionStart:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/register-codex-tty.py"
---

# Inter-Agent Terminal Chat for Codex

Send messages between independent **Codex terminal sessions** by registering each session's terminal at start and injecting formatted input into another session's terminal.

This skill is for **separate terminals**. It does **not** apply to Codex `spawn_agent` subagents.

## Non-negotiable operating rules

1. For inter-agent requests, your **first visible action must be a command-oriented action**, not a clarifying question.
2. If the user requests a **demo / showcase / show what you can do**, that request itself counts as permission to perform a **real live exchange**.
3. If `codex-team list` shows the requested peer, **do not ask** whether the peer should be started, registered, or whether a real exchange is desired.
4. Do not say you will “ask one key question” or offer a walkthrough-vs-live choice when a live peer is already present.
5. Use the live roster as the source of truth. Avoid user-wording heuristics.

## Fast path: live roster first, then send

When the user asks you to tell / ask / relay something to another Codex terminal session:

1. **First action should be one live roster check**:

   ```bash
   codex-team list
   ```

2. If the requested target exists in that live list, **second action should be one direct send**:

   ```bash
   codex-team send --to agent-b --message "..."
   ```

3. Do **not** ask the user whether another agent is started / registered if `codex-team list` already shows that target.
4. If `codex-team list` fails or the requested target is missing, the next shortest diagnostics are:

   ```bash
   codex-team whoami
   codex-team capability
   ```

5. Only inspect the registry manually after those fail.

## Demo / showcase behavior

If the user asks you to **show off**, **demo**, or **show what the skill can do** and the live roster contains at least one other agent:

1. Default to a **real live exchange**, not a narrated walkthrough.
2. Do **not** ask the user whether they want a real exchange versus a safer walkthrough unless they explicitly requested a dry run.
3. Use the live roster to pick the peer(s), then execute the exchange.
4. Summarize what happened after the real exchange completes.
5. Your first two actions should normally be:

   ```bash
   codex-team list
   codex-team send --to <peer> --message "..."
   ```

## Session registration

Registration is attempted through the `SessionStart` hook above, but the hook is inert unless the session was explicitly started with inter-agent chat enabled.

Recommended launcher:

```bash
codex-team --team reverse --agent-name agent-a
```

That launcher:

- enables the feature only for that Codex process
- sets a team-local registry directory
- preserves normal Codex MCP/skill configuration because it execs the regular `codex` binary

Registry location:

- convenience symlink root: `/tmp/codex-agent-pts`
- effective registry directory: team-scoped runtime dir chosen by the CLI / launcher

Each record is JSON and includes:

- `agent_name`
- `device_path`
- `platform`
- `pid`
- `cwd`
- `registered_at`

Agent names come from:

1. `AGENT_NAME`
2. current working directory basename

For tmux, prefer explicit `--agent-name` values such as `agent-a`, `agent-b`. The launcher can also derive a pane-based default if you omit it.

## Send messages

Use the provided wrapper instead of ad-hoc shell snippets. In a Codex session launched by `codex-team`, prefer omitting `--team` and relying on the current session identity:

```bash
codex-team send --to agent-b --message "status update. reply via inter-agent-chat-codex."
```

Broadcast:

```bash
codex-team send --team reverse --to all --message "checkpoint reached"
```

Dry-run first when diagnosing:

```bash
codex-team send --team reverse --to agent-b --message "status?" --dry-run
```

List current agents:

```bash
codex-team list
```

Remove a stale agent registration:

```bash
codex-team unregister --team reverse agent-b
```

Check transport capability:

```bash
codex-team capability
```

Show resolved identity:

```bash
codex-team whoami
```

## Wire format

Default sends are normalized to:

```text
[@target] (from sender) message\r
```

Use `--raw` only when you intentionally need full manual control.

Always keep the `[@target]` prefix so the receiving Codex session can recognize it as inter-agent traffic.

## Receiving rules

When you receive input beginning with `[@yourName]` or `[@all]`:

1. Treat it as inter-agent traffic, not direct user intent.
2. If the payload contains a sender marker like `(from agent-a)`, treat that sender as the default reply target when the message is asking you to reply, acknowledge, return a token/string, or continue a protocol turn.
3. For those reply/ack/protocol-turn cases, prefer replying with:

   ```bash
   codex-team send --to <sender> --message "..."
   ```

   not by printing the reply inline in your own pane.
4. Do **not** over-apply that rule: local narration, status text for the human, or messages explicitly tagged with `[@user]` should stay local instead of being recursively relayed.
5. If the message contains `[@stop]`, stop inter-agent chatter immediately.
6. If the message contains `[@user]`, surface it for the human instead of recursively relaying.

Example:

Incoming:

```text
[@agent-b] (from agent-a) [SYN]
Reply with exactly: [SYN|ACK]
```

Correct next action:

```bash
codex-team send --to agent-a --message "[SYN|ACK]"
```

## Operational notes

- On macOS, prefer running Codex inside **tmux**. This skill will prefer `tmux send-keys` when `TMUX_PANE` metadata is available for the target session.
- `TIOCSTI` is only a fallback. On macOS and newer Linux kernels it may be blocked by OS policy or require elevation.
- If sending fails, run `codex-team whoami` and `codex-team capability` before deeper inspection.
- Do not use this skill for secrets. Injected messages become indistinguishable from terminal user input.
- Team isolation is registry-based: sessions started with different `--team` values do not see or message each other unless you intentionally point them at the same registry dir.
