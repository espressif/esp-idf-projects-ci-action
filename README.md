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
