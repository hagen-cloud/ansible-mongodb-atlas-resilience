# Execution runbook

Last reviewed: 2026-10-07.

## Objective and scope

Operate a controlled primary failover or Azure regional outage test with standalone Ansible. The playbooks check control-plane state and recovery; operators must observe application behavior separately. This runbook does not authorize a real test.

## Prerequisites

- Install the pinned runtime on a Linux, macOS, or WSL control node and run from the repository root.
- Load `ansible.cfg`; on world-writable filesystems export `ANSIBLE_CONFIG="$PWD/ansible.cfg"` explicitly.
- Inject Atlas credentials into the control-node environment. Prefer service account client credentials. Do not store secrets in the vars file.
- Confirm API network access and any Atlas access-list requirements.
- Verify feature availability and permissions against the current official references. Primary failover is available for M10 or higher; regional outages are unavailable on Free and Flex deployments and require a suitable multi-region topology. The role's replica-set assumptions have not been validated on Atlas Infinite deployments.
- Obtain authorization for the exact target and maintenance window, and review expected blast radius and recovery ownership.
- Prepare an independent cleanup vars file and credentials before starting any outage.

Atlas documents Project Owner or Organization Owner access for regional outages; primary failover also allows Project Cluster Manager and Project Stream Processing Owner. Check every endpoint's required permissions for the identity used, including project resolution and monitoring.

## Primary failover

1. Copy `examples/primary_failover_vars.yml` to ignored `local-vars.yml` and set the exact project and cluster names.
2. Review the target, confirmation, monitoring, and approved maintenance window.
3. Run:

   ```bash
   ansible-playbook playbooks/primary_failover.yml -e @local-vars.yml
   ```

4. Confirm `CLUSTER_UPDATE_COMPLETED`, a new healthy primary for every replica set, `IDLE`, and a succeeded custom statistics result.
5. Review Atlas and application monitoring. A successful playbook is not proof of application availability or measured recovery objectives.

Input and readiness checks execute inside this invocation before the POST. There is no separate precheck command. Do not relaunch automatically after an uncertain POST response; first inspect Atlas events and state to determine whether the action was accepted.

## Regional outage

1. Copy `examples/regional_outage_vars.yml` to `local-vars-outage.yml`; set exact target names and Atlas Azure codes present in that topology.
2. Optionally set `atlas_allowed_outage_regions` to your reviewed operating policy. Choose duration 1, 3, or 7 days.
3. Keep `allow_majority_outage: false` unless an explicitly authorized test requires quorum loss. The role always rejects removing every electable node from a replica set.
4. Prepare `local-vars-cleanup.yml` from `examples/regional_outage_end_vars.yml` with the same target.
5. Run:

   ```bash
   ansible-playbook playbooks/regional_outage_start.yml -e @local-vars-outage.yml
   ```

6. Review the classification message and verify `SIMULATING`. Observe Atlas and application behavior for the approved test period.
7. End the simulation:

   ```bash
   ansible-playbook playbooks/regional_outage_end.yml -e @local-vars-cleanup.yml
   ```

8. Confirm simulation removal, recovery to `IDLE`, and application recovery. When the initial simulation read returns HTTP 404, cleanup reports already absent and does not independently poll cluster readiness; verify the target manually.

## Recovery and interruption

If start fails or the process is interrupted after Atlas may have accepted the request, inspect Atlas and invoke the independent cleanup playbook with the same target. An external runner should invoke it from its failure/finally path. Start does not automatically call cleanup, and a successful start deliberately leaves the simulation active for observation.

Cleanup waits through `START_REQUESTED` and `STARTING`, deletes a `SIMULATING` outage, and polls for removal and `IDLE`. It does not automatically recover a simulation in `FAILED`: inspect Atlas and escalate using the official procedure. Never guess a new target or repeatedly retry a mutating call after an uncertain response.

There is no reversal of a completed primary election. Regional recovery means ending the simulation; avoid topology changes outside a separately approved recovery procedure. Do not rely on expiration as timely cleanup: Atlas checks expiration in 24-hour intervals, so resolution can take an additional day.

## Risks and evidence

Quorum loss can interrupt writes and reads. Sharded-cluster regional outages may affect config-server availability. Keep logs containing project IDs, cluster names, simulation IDs, or topology counts private. Do not publish real run outputs. Check mode is unsupported and cannot preview these actions. Avoid partial execution with task skipping; use the documented complete entry points.

Record authorization, target, start/end times, observation evidence, cleanup result, and application recovery outside the source repository. Token expiration and monitoring permissions can interrupt polling; the role does not refresh OAuth tokens. Large projects may exceed the existing single-page process/event requests; pagination remains unchanged and unvalidated.

## Official references

- [Primary failover and prerequisites](https://www.mongodb.com/docs/atlas/tutorial/test-resilience/test-primary-failover/)
- [Regional outage, permissions, expiration, and recovery](https://www.mongodb.com/docs/atlas/tutorial/test-resilience/simulate-regional-outage/)
- [API authentication and token lifetime](https://www.mongodb.com/docs/atlas/api/api-authentication/)
- [Ansible control-node installation](https://docs.ansible.com/projects/ansible/latest/installation_guide/intro_installation.html)
