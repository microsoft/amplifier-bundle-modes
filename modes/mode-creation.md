---
mode:
  name: mode-creation
  description: Guided mode authoring with full mode spec loaded as context
  shortcut: mode-creation

  tools:
    safe:
      - read_file
      - glob
      - grep
      - write_file
      - edit_file
      - todo
      - load_skill

  default_action: block
---

@modes:context/modes-instructions.md

## Authoring a new mode

**Start by understanding intent:**
- What behaviour change does the user want?
- Is it restrictive (block risky tools), focused (one task only), or guided (inject domain knowledge)?

**Design the tool policy:**
- Always start from `default_action: block` — add back only what the task needs
- Match tools to the job: a read-only mode has no business with `write_file`
- Use `warn` for power tools you want available but surfaced consciously

**Write the body:**
- Be directive: explicit DO / DO NOT lists beat vague prose
- The `@namespace:path` pattern on its own line inlines file content at injection time — use it to load authoritative reference docs into context
- End with the exit path: `Use /mode off when done.`

**Save the file:**
- Project-specific: `.amplifier/modes/<name>.md`
- User-global: `~/.amplifier/modes/<name>.md`
- Bundle-shipped: `modes/<name>.md` (alongside `careful.md`, `plan.md`)
