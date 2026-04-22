# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `shortcut:` in mode frontmatter now defaults to the mode's `name` when omitted.
  Set `shortcut: false` to disable. Shortcuts are lowercased at parse time and validated
  against `^[a-z][a-z0-9_-]*$`; invalid values log a warning and register no alias (the
  mode remains activatable via `/mode <name>`). Modes that previously lacked a slash
  alias due to the missing field will now gain one; to restore the prior behavior, add
  an explicit `shortcut: false`. (Fixes silent failure mode where `/<mode-name>`
  returned `"Unknown command"`.)

### Known limitations

- Modes whose `name` matches a built-in CLI command (`help`, `mode`, `modes`, `exit`,
  `quit`, etc.) will register a default shortcut that is silently overridden by the
  CLI's command dispatch. These modes remain activatable via `/mode <name>`. To give
  such a mode a working slash alias, set `shortcut:` explicitly to a non-reserved value.

### Notes

- `shortcut: false` (YAML boolean) is opt-out. `shortcut: "false"` (quoted string) is a
  regular shortcut literally named `false` and will register `/false`. Use the
  unquoted boolean form to disable.
