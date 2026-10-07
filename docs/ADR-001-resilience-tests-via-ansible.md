# ADR-001: Run resilience tests through standalone Ansible

## Status

Accepted for the Hagen Cloud adaptation, 2026-10-07. Supersedes the inherited controller-specific execution decision. Version: 1.0.

## Context

MongoDB Atlas exposes primary failover and regional outage operations through its Admin API. The supplied tool already uses Ansible playbooks, a reusable role, custom filters, local execution, and environment-based authentication. A dedicated automation controller will no longer execute it.

## Decision

Use `ansible-playbook` on a Linux, macOS, or WSL control node. Preserve entry points, role structure, API requests, authentication precedence, polling, duration choices, quorum classification, one-shot mutations, and independent cleanup.

Name the repository `ansible-mongodb-atlas-resilience`, using lowercase words separated by hyphens and identifying both the framework and purpose. This is a repository-specific decision, not a new organization-wide naming standard.

Replace a fixed deployment region list with optional `atlas_allowed_outage_regions`, defaulting to regions validated against the target's effective Azure topology. Keep Azure-only support; adding providers would be a separate behavioral change.

Remove the inherited internal pipeline and replace it with validation-only GitHub Actions. Use environment variables for credentials and CLI extra-vars files for non-secret operator inputs. Preserve `set_stats` and enable CLI custom statistics. The operator or external runner owns approval, observation, and cleanup after failures or interruptions; the code does not enforce an external approval or add automatic cleanup.

## Consequences

The tool is independent of a controller and organization-specific pipeline templates. Existing action behavior remains, except that the old four-region restriction is configurable. The pre-existing Azure selections continue to work. Real Atlas execution is not part of adoption verification.

Use a private repository, retain proprietary metadata, and leave any public license or redistribution decision open. Branding and sanitization do not establish ownership or permission to redistribute the supplied source.

## References

- [Atlas primary failover](https://www.mongodb.com/docs/atlas/tutorial/test-resilience/test-primary-failover/)
- [Atlas regional outage](https://www.mongodb.com/docs/atlas/tutorial/test-resilience/simulate-regional-outage/)
- [Atlas API authentication](https://www.mongodb.com/docs/atlas/api/api-authentication/)
