# Operator input contract

Last reviewed: 2026-10-07.

## Common inputs

| Variable | Required | Validation or default |
|---|---|---|
| `project_name` | Yes | Exact Atlas project name, 1 to 64 characters. |
| `cluster_name` | Yes | Exact Atlas cluster name, nonempty. |
| `resilience_test` | Generic entry point | `primary_failover` or `regional_outage`; fixed action playbooks set it. |
| `confirmation` | Yes | `RUN_RESILIENCE_TEST` for start/failover, `END_OUTAGE_SIMULATION` for cleanup. |

The role resolves `project_id` with `GET /groups/byName/{project_name}`. Credentials belong in environment variables, not extra-vars files. No controller-specific credentials or prompts are required.

## Regional outage inputs

| Variable | Required | Validation or default |
|---|---|---|
| `outage_state` | Generic regional entry point | `started` or `absent`; defaults to `started`. Fixed start/end playbooks set it. |
| `outage_regions` | Start | Nonempty list or comma/newline-separated string of Atlas Azure region codes. |
| `atlas_allowed_outage_regions` | No | List; default `[]` accepts Azure regions in the target topology. Nonempty lists constrain selections. |
| `simulation_duration_days` | No | `1`, `3`, or `7`; defaults to `3`. Still validated during cleanup. |
| `allow_majority_outage` | No | `false` by default; `true` permits quorum loss only while at least one electable node remains in every replica set. |

Region values are Atlas codes, not Azure location names. Selection is normalized to uppercase, sorted, and checked against the effective cluster topology. A syntactically valid code absent from that topology is rejected before any start POST. Providers remain restricted to Azure.

## Runtime settings

Defaults are in `roles/mongodb_atlas_resilience/defaults/main.yml`: Atlas base URL, media version, TLS verification, HTTP timeout, polling intervals, and retry limits. Keep the default HTTPS endpoint and TLS verification for real runs. Endpoint overrides are intended for testing or explicitly reviewed environments.

`atlas_poll_interval_seconds` and `atlas_poll_retries` default to 30 and 50. Failover event polling defaults to 10 seconds and 60 retries. These are read-only polling controls; POST and DELETE are never automatically retried. Check mode is rejected before authentication.

## Results and approval

`set_stats` publishes a `mongodb_atlas_resilience` object with action, target identifiers, final status, and applicable counts or lifecycle fields. It excludes authentication material and full API responses, but contains operational identifiers and must remain private for real targets.

Confirmation strings and majority opt-in are required input guards. The role cannot verify a change ticket or external approval. An operator or runner must authorize the target, review impact, observe the result, and guarantee cleanup.
