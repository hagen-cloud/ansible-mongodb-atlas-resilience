# AGENTS.md — ansible-mongodb-atlas-resilience

## Project context

Hagen Cloud Ansible playbooks and a reusable role for controlled MongoDB Atlas primary failover and Azure regional outage tests through the Atlas Admin API. Execute with `ansible-playbook` on a Linux, macOS, or WSL control node.

## Code standards

- Keep code, comments, commit messages, and documentation in English.
- Preserve the entry points, role structure, one-shot mutations, polling, and cleanup behavior.
- Never store or log credentials, tokens, connection strings, or authorization headers.
- Every authentication and protected HTTP task must use `no_log: true`.
- Never retry mutating requests automatically. Retry only read-only status polling.
- Assertions must include descriptive `fail_msg` and `success_msg` values.
- Regional outage cleanup must treat HTTP 404 as already absent.
- Majority outage requires explicit operator authorization and `allow_majority_outage: true`; the role cannot enforce external approvals.
- Resolve selected regions against the effective target topology; optionally constrain them with `atlas_allowed_outage_regions`.
- Do not use `replSetStepDown`; use the Atlas failover API.
- Use conventional branch prefixes and never push directly to `master`.
- Keep operational identifiers and logs private. Do not add an open-source license without an explicit decision.
- Never call a real Atlas endpoint during repository verification.

## Verification

```bash
python -m unittest discover -s tests -v
ansible-playbook --syntax-check site.yml
ansible-playbook --syntax-check playbooks/primary_failover.yml
ansible-playbook --syntax-check playbooks/regional_outage.yml
ansible-playbook --syntax-check playbooks/regional_outage_start.yml
ansible-playbook --syntax-check playbooks/regional_outage_end.yml
yamllint .
ansible-lint --offline
```

Install the pinned runtime and test requirements. Integration tests use a loopback HTTP server with synthetic data and credentials; they require `ansible-playbook` on PATH.
