# The cache holds only settled facts

The cache stores two things: the merge requests a commit on the default branch belongs to, and the failed jobs of a
finished pipeline keyed by pipeline id and `updated_at`. Deployments, the branch head, tags, and unfinished pipelines
are fetched on every run. The trade is request count for correctness: caching the mutable data would save most of a
run's calls but make the report depend on cache age, while this split means a stale, lost, or concurrently
overwritten cache can only make a run slower, never wrong. The same rule lets the cache be pruned to what the last
run used and discarded outright on a schema change instead of migrated.
