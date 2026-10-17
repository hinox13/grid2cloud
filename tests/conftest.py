"""Suite-wide test configuration.

Some tests check frozen research artefacts that exist only in the gitignored local data folders
`data/raw` and `data/interim` (third-party inputs and intermediate outputs, which are never
redistributed; README §40). On a public clone those folders hold no research data, so a test that
opens such a file is reported as SKIPPED with the missing path, instead of failing.

The rule is deliberately narrow:
- it is active only when the local research data are absent (`PUBLIC_CLONE`);
- it converts only `FileNotFoundError` for a path inside `data/raw` or `data/interim`;
- every other error still fails.
On the research machine the data exist, the rule is off, and these tests run as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloud2grid.licensing.registry import REPO_ROOT

LOCAL_ROOTS = (REPO_ROOT / "data/raw", REPO_ROOT / "data/interim")
# sentinels: present on the research machine, never in the public repository
SENTINELS = (
    REPO_ROOT / "data/raw/ukpn/ltds_demand_3a.parquet",
    REPO_ROOT / "data/interim/e5/synthetic/manifest.parquet",
)
PUBLIC_CLONE = not any(p.exists() for p in SENTINELS)


def _local_missing(exc: BaseException) -> str | None:
    """The missing path, if `exc` is a FileNotFoundError inside the local data folders."""
    if not isinstance(exc, FileNotFoundError) or not exc.filename:
        return None
    path = Path(exc.filename)
    path = path if path.is_absolute() else REPO_ROOT / path
    if any(path.resolve().is_relative_to(r.resolve()) for r in LOCAL_ROOTS):
        return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if not PUBLIC_CLONE or call.excinfo is None or report.when not in ("setup", "call"):
        return
    missing = _local_missing(call.excinfo.value)
    if missing:
        report.outcome = "skipped"
        report.longrepr = (
            str(item.path),
            item.location[1] or 0,
            f"Skipped: needs local research data not in the public repository ({missing})",
        )
