# mongodb_atlas_resilience

Hagen Cloud role for MongoDB Atlas primary failover and Azure regional outage tests with `ansible.builtin.uri`. Run locally with standalone Ansible. See the repository README for installation, the input contract, and the execution runbook.

## Project resolution

Provide `project_name` and `cluster_name`; the role resolves the project ID before accessing the cluster.

## Modes

- Primary failover: `resilience_test: primary_failover`, `confirmation: RUN_RESILIENCE_TEST`. Validate `IDLE` and process health, capture primaries, submit one request, wait for the cluster update event, new primaries, and `IDLE`.
- Outage start: `resilience_test: regional_outage`, `outage_state: started`, `confirmation: RUN_RESILIENCE_TEST`. Select Azure `outage_regions` in the effective topology. Optional `atlas_allowed_outage_regions` constrains selections. Classify quorum impact, start or reuse a compatible outage, and wait for `SIMULATING`.
- Outage cleanup: `resilience_test: regional_outage`, `outage_state: absent`, `confirmation: END_OUTAGE_SIMULATION`. End the simulation idempotently; accept HTTP 404 as already absent.

## Security and execution

Inject environment credentials for OAuth or HTTP Digest. Protected HTTP tasks use `no_log: true`; results use `set_stats` and contain operational identifiers that must remain private. Approval and guaranteed cleanup belong to the operator or external runner. Majority opt-in does not enforce external approval. Mutations are not automatically retried, and check mode is rejected.

The role retains Azure-only regional support and the existing duration, polling, topology, and recovery algorithms. Live API compatibility has not been certified by offline tests.
