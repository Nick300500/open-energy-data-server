# netallocation: vendored copy — local patches

This `netallocation/` directory is a **vendored copy** of
[FRESNA/netallocation](https://github.com/FRESNA/netallocation), used for consumption-side
flow-tracing (allocating emissions to where power was *consumed*). Not currently in scope for
the generation/production-side modularization work, but compared here on request (2026-07-15).

⚠️ **Stale version string:** `netallocation/__init__.py` declares `__version__ = "0.0.8"`, but
the code content actually matches the GitHub **`master`** branch, not the `0.0.8` PyPI release
(PyPI 0.0.8 differs substantially — hundreds of lines per file — from both `master` and this
vendored copy). The version string was likely never bumped after this was vendored from a
later `master` checkout. Don't trust `__version__` here as a reliable pin.

## How this was verified

Cloned `master` and diffed CRLF/LF-neutrally against the local files. Because raw diffs showed
every file as "different", both sides were additionally normalized with the same `black`/
`isort` formatting to separate real logic changes from pure reformatting noise:

```bash
git clone --depth 1 https://github.com/FRESNA/netallocation.git /tmp/netalloc_master
python -m black -q /tmp/netalloc_master/netallocation/*.py
python -m isort -q /tmp/netalloc_master/netallocation/*.py
python -m black -q /tmp/netalloc_master/netallocation/*.py   # isort can un-format black's output
diff <(tr -d '\r' < netallocation/FILE.py) <(tr -d '\r' < /tmp/netalloc_master/netallocation/FILE.py)
```

## Result: near-identical to `master`

After formatting normalization, **12 of 15 files are byte-identical** to `master`
(`__init__.py`, `breakdown.py`, `common.py`, `evaluate.py`, `grid.py`, `io.py`, `linalg.py`,
`plot.py`, `plot_helpers.py`, `process.py`, `test.py`, `utils.py`). The raw (pre-normalization)
diffs of hundreds of changed lines per file were essentially all import-sorting and quote-style
(`black`/`isort`) noise — not real changes.

Only 2 files have genuine logic differences from `master`:

### `cost.py`
`allocate_carrier_attribute(ds, n, attr)` gained an extra local `sparse=False` parameter:

```python
def allocate_carrier_attribute(ds, n, attr, sparse=False):
    ...
    attrs = DataArray(n.carriers[attr], dims="source_carrier")
    if sparse:
        attrs = as_sparse(attrs)
    return attrs * ds
```

vs upstream's unconditional `return DataArray(n.carriers[attr], dims="source_carrier") * ds`.
**Why:** not confirmed with Nick — looks like an intentional feature addition to support sparse
arrays for large networks, worth checking if it was ever actually exercised (`sparse=True`
call sites) before assuming it's dead code.

### `flow.py`
The Gurobi solver name passed to `n.lopf(...)` differs:

- local: `solver_name="gurobi"`
- upstream `master`: `solver_name="gurobi_persistent"`

**Why:** not confirmed — could be a deliberate downgrade to the simpler (non-persistent)
Gurobi interface for compatibility/performance reasons, or could be stale/accidental. Since
this only affects the consumption-side flow-tracing LOPF re-solve (out of scope for now), not
investigated further.

## Not investigated

`convert.py` has a single blank-line diff (no real change). Behavioral equivalence of the two
real diffs above (`cost.py` sparse handling, `flow.py` solver choice) was not tested at
runtime — flagged for whoever picks up consumption-side work.
