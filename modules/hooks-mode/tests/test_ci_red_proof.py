"""DELIBERATE DEFECT -- scratch branch only. Proves the CI gate can go RED.

This file exists on branch ci/red-proof-j1e6 and nowhere else. It plants two
independent, deliberate failures:

  1. a genuine TEST failure, so the test job's log shows the real suite
     collecting and executing ("N passed, 1 failed") rather than erroring out
     during setup -- a setup or import error would prove nothing.
  2. an unused import, so the pinned ruff gate reports F401.

The branch also breaks behaviors/zz-ci-red-proof.yaml, so the bundle-structure
job goes red for its own reason.

Delete this file, and the branch, once the red run is observed.
"""

from __future__ import annotations

import json  # noqa-free on purpose: unused, so ruff F401 fires


def test_ci_red_proof_deliberate_failure() -> None:
    """Always fails. Proves the test job gates on a real assertion."""
    assert 1 == 2, (
        "DELIBERATE FAILURE (ci/red-proof-j1e6): if you are reading this in a "
        "CI log, the test job is executing the real suite and gating on it."
    )
