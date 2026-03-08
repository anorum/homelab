# Claude Code Local Model Switching

## Problem
On Claude Pro ($20/mo), usage limits hit periodically. When limited, Claude Code is unusable. Need a way to fall back to local Ollama models on the Mac Mini (192.168.1.105) for continued coding.

## Solution
Shell functions in `.zshrc` that switch Claude Code between Anthropic and Ollama.

Ollama now has native Anthropic-compatible API support (see https://docs.ollama.com/integrations/claude-code), so no gateway needed.

## Design

### Shell functions (added to ~/.zshrc)

**`claude-local`** — Launch Claude Code against Ollama on Mac Mini:
```bash
claude-local() {
  ANTHROPIC_BASE_URL=http://192.168.1.105:11434 \
  ANTHROPIC_AUTH_TOKEN=ollama \
  ANTHROPIC_API_KEY="" \
  claude --model qwen3-coder "$@"
}
```

**`claude-cloud`** — Explicit Anthropic launch (optional, since `claude` already does this):
```bash
claude-cloud() {
  unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN
  claude "$@"
}
```

### Model: qwen3-coder
- Recommended by Ollama for Claude Code
- Good tool calling support (required for file editing, bash, etc.)
- Needs 64k+ context window — Mac Mini with Apple Silicon should handle this

### Taskfile task to pull the model
```yaml
ollama:pull-coder:
  desc: Pull qwen3-coder model for Claude Code local use
  cmds:
    - curl -s {{.OLLAMA_HOST}}/api/pull -d '{"name":"qwen3-coder"}' | ...
```

## Files to modify
| File | Change |
|------|--------|
| `~/.zshrc` | Add `claude-local` and `claude-cloud` functions |
| `Taskfile.yml` | Add `ollama:pull-coder` task |

## Verification
1. `task ollama:pull-coder` — pull qwen3-coder on Mac Mini
2. `claude-local` — should launch Claude Code against Ollama
3. Ask it to read a file and make an edit — confirms tool use works
4. `claude` (normal) — still works against Anthropic
