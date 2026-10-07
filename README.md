# ansible-mongodb-atlas-resilience

Hagen Cloud Ansible tooling for controlled MongoDB Atlas resilience tests through the Atlas Admin API. Run primary failover and Azure regional outage simulations from a Linux, macOS, or WSL control node using `ansible-playbook`.

## Capabilities

- Resolve the project ID from the exact project name and validate the cluster before a mutation.
- Submit a single `restartPrimaries` request; wait for `CLUSTER_UPDATE_COMPLETED`, different healthy primaries in every replica set, and cluster state `IDLE`.
- Classify regional outage impact per replica set or shard using effective topology.
- Accept Atlas Azure region codes present in the target topology, with an optional operator allowlist.
- Reject duplicate selections, unknown topology regions, and loss of every electable node in any replica set.
- Block majority outages unless `allow_majority_outage: true` is explicitly set.
- Start or reuse a compatible simulation, wait for `SIMULATING`, and end it with idempotent cleanup that accepts HTTP 404.
- Report operational results through `ansible.builtin.set_stats`, visible in the CLI custom statistics recap.

The role structure, entry points, authentication precedence, API operations, polling, duration choices (1, 3, or 7 days), and cleanup lifecycle are preserved. Regional outages remain Azure-only; other cloud providers are outside this adaptation.

## Install

Use Python 3.12 or newer on a supported Ansible control node. On Windows, run these commands inside WSL. The pinned runtime is the tested baseline; earlier Ansible versions are not certified.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r runtime-requirements.txt
```

All modules are built into `ansible-core`; `requirements.yml` intentionally declares no external collections or roles. Run from the repository root so Ansible loads `ansible.cfg`, `roles/`, and `filter_plugins/`. If the filesystem is world-writable (common with WSL-mounted Windows folders), explicitly export `ANSIBLE_CONFIG="$PWD/ansible.cfg"`.

## Authentication

Inject credentials into the control-node environment through a secret manager or secure interactive session:

| Environment variables | Method |
|---|---|
| `MONGODB_ATLAS_CLIENT_ID` and `MONGODB_ATLAS_CLIENT_SECRET` | Service account OAuth; recommended. |
| `MONGODB_ATLAS_ACCESS_TOKEN` | Pre-issued OAuth token. Takes precedence over other methods. |
| `MONGODB_ATLAS_PUBLIC_KEY` and `MONGODB_ATLAS_PRIVATE_KEY` | Legacy HTTP Digest API keys; used when no token or complete OAuth pair is supplied. |

Do not pass secrets in extra vars, shell command arguments, or committed files. Protected HTTP requests use `no_log: true`. Tokens are acquired once per execution; they are not refreshed during polling. Supply a token with enough remaining lifetime or use the client credentials flow.

## Entry points

| Playbook | Purpose |
|---|---|
| `site.yml` | Generic entry point using `resilience_test` and `outage_state`. |
| `playbooks/primary_failover.yml` | Primary failover. |
| `playbooks/regional_outage.yml` | Regional outage, selected state. |
| `playbooks/regional_outage_start.yml` | Outage start. |
| `playbooks/regional_outage_end.yml` | Independent outage cleanup. |

Every play runs on `localhost`, uses `connection: local`, and disables fact gathering. Generic entry points require the appropriate action variables; fixed entry points set their action but still require explicit confirmation.

Copy an example to an ignored local file and replace the synthetic names with your approved target:

```bash
cp examples/primary_failover_vars.yml local-vars.yml
# Edit local-vars.yml and review the target before executing.
ansible-playbook playbooks/primary_failover.yml -e @local-vars.yml
```

For regional outage, use `examples/regional_outage_vars.yml` with the start entry point. End the simulation independently with `examples/regional_outage_end_vars.yml` and the end entry point. Examples contain execution confirmations and must be reviewed before use.

Read [the input contract](docs/input-contract.md) and [the execution runbook](docs/execution-runbook.md) before any real execution. There is no standalone precheck or external approval engine in this repository: validations run inside the selected action before the mutation. Start and cleanup are separate invocations; the operator or an external runner must guarantee cleanup after a start attempt, including failure or interruption.

## Verification

```bash
python -m pip install -r test-requirements.txt
python -m unittest discover -s tests -v
ansible-playbook --syntax-check site.yml
ansible-playbook --syntax-check playbooks/primary_failover.yml
ansible-playbook --syntax-check playbooks/regional_outage.yml
ansible-playbook --syntax-check playbooks/regional_outage_start.yml
ansible-playbook --syntax-check playbooks/regional_outage_end.yml
yamllint .
ansible-lint --offline
```

The GitHub workflow only validates source and runs tests against a local mock server. It has no Atlas credentials and never performs resilience tests against Atlas. See [the adoption review](docs/adoption-review.md) for verified results and remaining limitations.

## Operational boundaries

Mutating calls are never retried automatically; only reads are polled. Check mode is explicitly rejected and is not a preview. Majority opt-in is an input guard, not proof of an external approval. Results include project and cluster identifiers and topology counts; keep run logs and CI artifacts containing real execution data private.

The existing API media version `2025-03-12` is retained and configurable. Live compatibility, permissions, and application resilience must be validated in a separately authorized sandbox. Repository verification does not establish production readiness. No public reuse license has been selected; the role retains its proprietary license metadata.

## References

- [Atlas primary failover](https://www.mongodb.com/docs/atlas/tutorial/test-resilience/test-primary-failover/)
- [Atlas regional outage](https://www.mongodb.com/docs/atlas/tutorial/test-resilience/simulate-regional-outage/)
- [Atlas API authentication](https://www.mongodb.com/docs/atlas/api/api-authentication/)
- [Ansible installation and control-node requirements](https://docs.ansible.com/projects/ansible/latest/installation_guide/intro_installation.html)

Last reviewed: 2026-10-07.
