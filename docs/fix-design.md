# Fix Design: False-positive Mode Warning After `/mode off`

## Root Cause

The false-positive warning is triggered by the B3 guard in `hooks-mode/__init__.py:640-643`, which checks whether the `RuntimeOverlay` **object** exists (`is not None`) rather than whether it has active scope claims. 

The `RuntimeOverlay` is designed as a session-lifetime singleton that intentionally persists after `/mode off` to maintain coherent refcounts across activations/deactivations within a single session. When a mode is deactivated with `/mode off`:

1. `overlay.revoke()` properly empties the `_scope_claims` dictionary
2. `active_mode` is correctly set to `None`
3. BUT the overlay **object** itself remains non-None (by design)

This causes the guard to fire on every subsequent turn, warning about "possible session-resume state loss" even though mode contributions were properly revoked.

The guard's stated purpose (detecting process-restart/session-resume state loss) is logically unreachable: if the process restarts, both `active_mode` and `mode_runtime_overlay` would be `None` (both live in-process memory), so the warning would never fire from a genuine resume scenario.

## Files to Change

- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (around line 640)

## Suggested Fix

Replace the guard condition to check both object existence AND non-empty `_scope_claims`:

**Before (triggers false positive after every normal `/mode off`):**
```python
if self.coordinator.session_state.get("mode_runtime_overlay") is not None:
```

**After (only warns when contributions are still registered without active_mode):**
```python
overlay_obj = self.coordinator.session_state.get("mode_runtime_overlay")
if overlay_obj is not None and getattr(overlay_obj, "_scope_claims", None):
```

## Impact

- **Scope:** Single-line change in one file
- **Risk:** Minimal - maintains the original intent (detecting orphaned contributions) while eliminating false positives
- **Testing:** After fix, `/mode off` should not trigger warnings on subsequent turns
- **API Surface:** No changes to public API or contracts

## Secondary Issues (Out of Scope)

Two additional issues were noted during triage but are not addressed by this fix:

1. **`active_mode` never written to `session:config`** - remains `null` even during active mode
2. **Warning not emitted as structured event** - only logged via `logger.warning()`, invisible in `events.jsonl`

These are independent issues that should be tracked separately.
