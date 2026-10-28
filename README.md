# ESP-IDF projects CI action

Composite GitHub Action that initializes git submodules **shallow, in
parallel, with retries**, backed by a cache shared across the whole workflow
run.

ESP-IDF component projects vendor upstream libraries as git submodules, and
every build shard used to fetch all of them from the network. This action
fetches them once per workflow run into a shared cache; build shards restore
the cache and materialize working trees from it offline.

## Usage

Add one cache-populating job to the caller workflow. It is the single writer:
submodule content depends only on the recorded gitlink hashes, so one
populate serves every matrix invocation of downstream jobs.

```yaml
jobs:
  submodules:
    name: Populate submodule cache
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5
      - name: Populate submodule cache
        uses: espressif/esp-idf-projects-ci-action@v1
        with:
          save-cache: 'true'
          materialize: 'false'
```

Build jobs (including jobs running in containers) restore the cache and
check out the submodule working trees:

```yaml
  build:
    needs: submodules
    runs-on: ubuntu-22.04
    container: espressif/idf:release-v5.4
    steps:
      # No submodules: 'true' here; the action replaces it.
      - uses: actions/checkout@v5
      - name: Init submodules (shallow, cached, with retry)
        uses: espressif/esp-idf-projects-ci-action@v1
```

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `save-cache` | `'false'` | Save the cache after fetching; enable in exactly one job per run |
| `materialize` | `'true'` | Check out working trees even on a cache hit; populating jobs set `'false'` |

## Outputs

| Output | Meaning |
| --- | --- |
| `cache-hit` | `'true'` when the cache was restored |
| `cache-key` | Full cache key, `submodules-<gitlink hash>` |

## Design

- The cache key hashes all submodule pointers in the tree
  (`git ls-tree -r HEAD` gitlinks), so it changes exactly when a submodule is
  bumped and is independent of the SDK version or build shard. Restore never
  uses `restore-keys`: a partial match would silently mix submodule versions.
- Only `.git/modules` is cached. Restoring it gives git the shallow submodule
  clones; `git submodule update --init` then materializes working trees from
  them without network access.
- Fetch is `git submodule update --init --force --depth 1 --jobs 8` with
  protocol v2, retried three times. After repeated failure each submodule is
  retried individually so the log names the exact submodule and its error.
  This mirrors `actions/checkout`'s `submodules: 'true'` (which fetches at
  depth 1) while adding parallelism and resilience.
- `actions/cache` scopes entries to the ref; the populating job and its
  consumers share a scope by running in the same workflow run. Cache save is
  best-effort: a concurrent run populating the same key stores identical
  content.
- Repos without submodules get an empty-key cache miss and a no-op update;
  the action is safe to use unconditionally.

Requires `bash` and `git` in the job environment, and an
`actions/checkout` of the target repository beforehand. Works in Linux
container jobs (adds its own `safe.directory` exception, which
`actions/checkout`'s temporary one does not cover).

# Reusable workflows

This repository also hosts the ESP-IDF component project CI pipeline as two
[reusable workflows](https://docs.github.com/en/actions/using-workflows/reusing-workflows):

- `.github/workflows/build_and_run_apps.yml` — the full pipeline: change
  detection from PR labels and diffs, the submodule cache populate job, one
  `reusable-ci.yml` invocation per SDK version, aggregate reports and a
  stable `CI Gate` status check.
- `.github/workflows/reusable-ci.yml` — the per-SDK pipeline: coverage
  audit, per-target build shards, test planning, hardware/QEMU/host test
  workers, JUnit and HTML reports. Can also be called directly.

## Consumer setup

Workflow triggers must live in the consuming repository, so each consumer
keeps a thin caller workflow:

```yaml
name: Build and Run Apps

on:
  pull_request:
    types: [opened, reopened, synchronize]
  push:
    branches:
      - master

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  pipeline:
    name: CI pipeline
    permissions:
      contents: read
      pull-requests: write
      checks: write
      actions: read
    uses: espressif/esp-idf-projects-ci-action/.github/workflows/build_and_run_apps.yml@v1

  # Preserves the stable 'CI Gate' check name for branch protection.
  ci-gate:
    name: CI Gate
    if: always()
    needs: pipeline
    runs-on: ubuntu-22.04
    steps:
      - run: test "${{ needs.pipeline.result }}" != "failure" && test "${{ needs.pipeline.result }}" != "cancelled"
```

Consumers supply in their own repository:

- `.github/ci-matrix.json` — the SDK Docker tags to build and test against
  (`[{"idf_version": "release-v5.4"}, ...]`)
- `.idf_build_apps.toml`, `.build-test-rules.yml`, manifests
- pytest configuration (`pytest.ini`, root `conftest.py`) and test apps

The pipeline checks out the consumer repository and runs in its context:
caches, artifacts, PR labels (`PR: test all apps`, `PR: build only`) and
tokens are the consumer's. CI helpers (`.github/actions/ci-tools`,
`setup-idf-build-env`, `get_ci_changes.py`) are fetched from the exact
revision of the called workflow, so every consumer runs the same tooling.
The caller workflow above documents the permission superset the called jobs
need; job-level permissions inside the pipeline narrow it further.

Pipeline behavior (change selection, shards, planning, reports, artifacts)
is documented in
[idf-extra-components](https://github.com/espressif/idf-extra-components/blob/master/.github/readme_workflows.md).
