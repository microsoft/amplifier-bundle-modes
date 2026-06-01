# Fix Plan: False-positive Mode Warning After `/mode off`

## FILES TO CHANGE

### `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`

**Location:** Line ~640 (in the B3 guard section)

**Current code:**
```python
if self.coordinator.session_state.get("mode_runtime_overlay") is not None:
    logger.warning(
        "Mode runtime overlay exists but active_mode is None — "
        "possible session-resume state loss. Mode contributions will not be injected this turn."
    )
```

**Updated code:**
```python
overlay_obj = self.coordinator.session_state.get("mode_runtime_overlay")
if overlay_obj is not None and getattr(overlay_obj, "_scope_claims", None):
    logger.warning(
        "Mode runtime overlay exists but active_mode is None — "
        "possible session-resume state loss. Mode contributions will not be injected this turn."
    )
```

**Change explanation:** Add a second condition to check if `_scope_claims` is non-empty, ensuring the warning only fires when there are actual orphaned contributions, not when the overlay is an empty singleton after clean deactivation.

## TESTS

### Tests to Add/Modify

1. **Test: No warning after clean mode deactivation**
   - Location: `modules/hooks-mode/tests/` (look for existing test file or create `test_mode_lifecycle.py`)
   - Test case:
     ```python
     def test_no_warning_after_mode_off():
         # Activate a mode
         # Deactivate with /mode off
         # Send subsequent messages
         # Assert no "Mode runtime overlay exists but active_mode is None" warning
     ```

2. **Test: Warning fires for genuine state mismatch**
   - Location: Same test file
   - Test case:
     ```python
     def test_warning_on_orphaned_contributions():
         # Create scenario where overlay has _scope_claims but active_mode is None
         # Assert warning is triggered
     ```

3. **Regression test: Normal mode activation/deactivation cycle**
   - Verify the fix doesn't break existing mode functionality
   - Test activation, tool blocking, deactivation, and contribution cleanup

## VERIFICATION

### Manual Testing Steps

1. **Test clean deactivation (main fix verification):**
   ```bash
   # Start Amplifier session
   amplifier run
   
   # In session:
   /mode brainstorm
   # (send a message, verify mode is active)
   /mode off
   # Send 3-4 more messages
   
   # Expected: No warnings in output or events.jsonl
   ```

2. **Check events.jsonl:**
   ```bash
   # Verify no false-positive warnings logged
   grep -i "Mode runtime overlay exists but active_mode is None" ~/.amplifier/sessions/<session-id>/events.jsonl
   # Should return nothing after /mode off
   ```

3. **Verify mode functionality still works:**
   ```bash
   # Activate mode again
   /mode brainstorm
   # Verify tool policies are enforced
   # Deactivate
   /mode off
   # Verify clean state
   ```

4. **Code review:**
   - Verify the guard now checks both object existence AND non-empty `_scope_claims`
   - Confirm the warning message and logic remain unchanged otherwise

### Success Criteria

- ✅ No warnings after `/mode off` on subsequent turns
- ✅ Mode activation/deactivation continues to work correctly
- ✅ RuntimeOverlay properly persists across mode cycles
- ✅ Warning still fires if genuine orphaned contributions exist (edge case)
- ✅ All existing tests continue to pass
