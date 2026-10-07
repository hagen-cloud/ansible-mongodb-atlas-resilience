import re
from datetime import datetime, timedelta, timezone

try:
    from ansible.errors import AnsibleFilterError
except ImportError:
    class AnsibleFilterError(ValueError):
        pass


_SUPPORTED_DURATIONS = {1, 3, 7}
_SUPPORTED_PROVIDERS = {"AZURE"}


def atlas_expiration_date(days, current_time=None):
    try:
        duration = int(days)
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError("Simulation duration must be 1, 3, or 7 days") from exc
    if duration not in _SUPPORTED_DURATIONS:
        raise AnsibleFilterError("Simulation duration must be 1, 3, or 7 days")
    current = current_time or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    expires = current.astimezone(timezone.utc) + timedelta(days=duration)
    return expires.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def atlas_normalize_outage_filters(filters):
    if not isinstance(filters, list) or not filters:
        raise AnsibleFilterError("At least one outage filter is required")
    normalized = []
    seen = set()
    for item in filters:
        if not isinstance(item, dict):
            raise AnsibleFilterError("Each outage filter must be an object")
        provider = str(item.get("cloudProvider", item.get("cloud_provider", ""))).upper().strip()
        region = str(item.get("regionName", item.get("region_name", ""))).upper().strip()
        filter_type = str(item.get("type", "REGION")).upper().strip()
        if provider not in _SUPPORTED_PROVIDERS:
            raise AnsibleFilterError("Outage filter cloud provider must be AZURE")
        if not region:
            raise AnsibleFilterError("Outage filter region name is required")
        if filter_type != "REGION":
            raise AnsibleFilterError("Only REGION outage filters are supported")
        key = (provider, region)
        if key in seen:
            raise AnsibleFilterError(f"Outage filter contains duplicate region {provider}/{region}")
        seen.add(key)
        normalized.append({"cloudProvider": provider, "regionName": region, "type": "REGION"})
    return sorted(normalized, key=lambda item: (item["cloudProvider"], item["regionName"]))


def atlas_azure_outage_filters(regions, allowed_regions=None):
    if isinstance(regions, str):
        region_codes = [item for item in re.split(r"[\s,]+", regions) if item]
    elif isinstance(regions, list):
        region_codes = regions
    else:
        raise AnsibleFilterError("Outage regions must be a list or comma-separated string")
    if not region_codes:
        raise AnsibleFilterError("At least one outage region is required")
    normalized_regions = [str(item).upper().strip() for item in region_codes]
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", region) for region in normalized_regions):
        raise AnsibleFilterError("Outage region must be an Atlas Azure region code")
    if allowed_regions is not None and not isinstance(allowed_regions, list):
        raise AnsibleFilterError("Allowed outage regions must be a list")
    allowlist = {str(item).upper().strip() for item in allowed_regions or []}
    if allowlist and any(region not in allowlist for region in normalized_regions):
        raise AnsibleFilterError("Outage region must be a supported Atlas Azure region in the configured allowlist")
    if len(set(normalized_regions)) != len(normalized_regions):
        raise AnsibleFilterError("Outage regions contain a duplicate selection")
    return atlas_normalize_outage_filters(
        [
            {
                "cloudProvider": "AZURE",
                "regionName": region,
                "type": "REGION",
            }
            for region in normalized_regions
        ]
    )


def atlas_cluster_process_summary(processes, cluster_name):
    prefix = f"{cluster_name}-".lower()
    target_processes = [
        process
        for process in processes or []
        if str(process.get("userAlias", "")).lower().startswith(prefix)
    ]
    replica_sets = {}
    for process in target_processes:
        replica_set = process.get("replicaSetName")
        if replica_set:
            replica_sets.setdefault(replica_set, []).append(process)
    primary_types = {"REPLICA_PRIMARY", "SHARD_PRIMARY"}
    unhealthy_types = {"RECOVERING", "NO_DATA"}
    monitored_sets = {
        name: members
        for name, members in replica_sets.items()
        if any(
            member.get("typeName") in primary_types
            or member.get("typeName") in {"REPLICA_SECONDARY", "SHARD_SECONDARY"}
            or member.get("typeName") in unhealthy_types
            for member in members
        )
    }
    primary_hosts = sorted(
        str(process.get("hostname"))
        for members in monitored_sets.values()
        for process in members
        if process.get("typeName") in primary_types
    )
    unhealthy_processes = sorted(
        str(process.get("hostname"))
        for members in monitored_sets.values()
        for process in members
        if process.get("typeName") in unhealthy_types
    )
    primary_count_by_set = {
        name: sum(member.get("typeName") in primary_types for member in members)
        for name, members in monitored_sets.items()
    }
    healthy = bool(monitored_sets) and not unhealthy_processes and all(
        count == 1 for count in primary_count_by_set.values()
    )
    return {
        "healthy": healthy,
        "processCount": sum(len(members) for members in monitored_sets.values()),
        "replicaSetCount": len(monitored_sets),
        "primaryHosts": primary_hosts,
        "unhealthyProcesses": unhealthy_processes,
        "primaryCountByReplicaSet": primary_count_by_set,
    }


def atlas_classify_outage(replication_specs, filters):
    normalized_filters = atlas_normalize_outage_filters(filters)
    selected = {(item["cloudProvider"], item["regionName"]) for item in normalized_filters}
    known = set()
    impacts = []
    for index, spec in enumerate(replication_specs or []):
        total = 0
        affected = 0
        region_configs = spec.get("regionConfigs", spec.get("region_configs", []))
        for config in region_configs or []:
            provider = str(config.get("providerName", config.get("provider_name", ""))).upper()
            region = str(config.get("regionName", config.get("region_name", ""))).upper()
            key = (provider, region)
            known.add(key)
            electable = config.get("electableSpecs", config.get("electable_specs", {})) or {}
            count = int(electable.get("nodeCount", electable.get("node_count", 0)) or 0)
            total += count
            if key in selected:
                affected += count
        if total <= 0:
            raise AnsibleFilterError("Each replication spec must contain electable nodes")
        remaining = total - affected
        if remaining <= 0:
            raise AnsibleFilterError("Regional outage must leave at least one electable node in each replica set")
        impacts.append(
            {
                "replicationSpecId": str(spec.get("id", index)),
                "scope": "none" if not affected else "majority" if affected * 2 >= total else "minority",
                "totalElectableNodes": total,
                "affectedElectableNodes": affected,
                "remainingElectableNodes": remaining,
            }
        )
    if not impacts:
        raise AnsibleFilterError("Cluster topology has no replication specs")
    unknown = [item for item in normalized_filters if (item["cloudProvider"], item["regionName"]) not in known]
    total = sum(item["totalElectableNodes"] for item in impacts)
    affected = sum(item["affectedElectableNodes"] for item in impacts)
    remaining = sum(item["remainingElectableNodes"] for item in impacts)
    if any(item["scope"] == "majority" for item in impacts):
        scope = "majority"
    elif affected:
        scope = "minority"
    else:
        scope = "none"
    return {
        "scope": scope,
        "totalElectableNodes": total,
        "affectedElectableNodes": affected,
        "remainingElectableNodes": remaining,
        "unknownFilters": unknown,
        "outageFilters": normalized_filters,
        "replicationSpecImpacts": impacts,
    }


class FilterModule:
    def filters(self):
        return {
            "atlas_expiration_date": atlas_expiration_date,
            "atlas_normalize_outage_filters": atlas_normalize_outage_filters,
            "atlas_azure_outage_filters": atlas_azure_outage_filters,
            "atlas_cluster_process_summary": atlas_cluster_process_summary,
            "atlas_classify_outage": atlas_classify_outage,
        }
