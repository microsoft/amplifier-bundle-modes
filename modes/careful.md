---
mode:
  name: careful
  description: Full capability with confirmation for destructive actions
  shortcut: careful
  
  tools:
    safe:
      - read_file
      - glob
      - grep
      - web_search
      - web_fetch
      - load_skill
      - LSP
      - python_check
      - todo
      - delegate
      - recipes
    confirm:
      - write_file
      - edit_file
      - bash
  
  default_action: block
---

CAREFUL MODE: Work normally, but confirm before destructive actions.

You have full capabilities, but the following require user approval:
- Writing or editing files
- Executing bash commands

This mode is for high-stakes work where you want AI assistance but with explicit checkpoints before any changes are made.

Workflow:
1. Analyze and plan as normal
2. When ready to make a change, the approval system will prompt
3. User reviews and approves/denies each action
4. Continue with approved actions

Best for:
- Production configuration changes
- Security-sensitive code modifications
- Unfamiliar codebases
- Learning how the AI approaches problems

Use /mode off to disable confirmations and work at full speed.
