import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


PLUGIN_PATH = Path(__file__).parents[1] / "filter_plugins" / "resilience.py"
SPEC = importlib.util.spec_from_file_location("resilience", PLUGIN_PATH)
resilience = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resilience)


class ExpirationDateTests(unittest.TestCase):
    def test_adds_supported_duration_in_utc(self):
        current = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            resilience.atlas_expiration_date(3, current),
            "2026-10-01T12:00:00Z",
        )

    def test_rejects_unsupported_duration(self):
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "1, 3, or 7"):
            resilience.atlas_expiration_date(2)


class OutageFilterTests(unittest.TestCase):
    def test_normalizes_and_sorts_filters(self):
        filters = [
            {"cloud_provider": "azure", "region_name": "europe_west"},
            {"cloudProvider": "AZURE", "regionName": "US_EAST_2", "type": "REGION"},
        ]
        self.assertEqual(
            resilience.atlas_normalize_outage_filters(filters),
            [
                {"cloudProvider": "AZURE", "regionName": "EUROPE_WEST", "type": "REGION"},
                {"cloudProvider": "AZURE", "regionName": "US_EAST_2", "type": "REGION"},
            ],
        )

    def test_rejects_duplicate_filters(self):
        filters = [
            {"cloud_provider": "AZURE", "region_name": "EUROPE_WEST"},
            {"cloudProvider": "azure", "regionName": "europe_west"},
        ]
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "duplicate"):
            resilience.atlas_normalize_outage_filters(filters)

    def test_rejects_non_azure_provider(self):
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "must be AZURE"):
            resilience.atlas_normalize_outage_filters(
                [{"cloud_provider": "AWS", "region_name": "US_EAST_1"}]
            )


class AzureOutageRegionTests(unittest.TestCase):
    def test_accepts_other_azure_region_without_deployment_allowlist(self):
        self.assertEqual(
            resilience.atlas_azure_outage_filters(["brazil_south"]),
            [{"cloudProvider": "AZURE", "regionName": "BRAZIL_SOUTH", "type": "REGION"}],
        )

    def test_rejects_invalid_region_code_and_invalid_allowlist_type(self):
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "region code"):
            resilience.atlas_azure_outage_filters(["https://example.invalid"])
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "must be a list"):
            resilience.atlas_azure_outage_filters(["EUROPE_WEST"], "EUROPE_WEST")

    def test_accepts_all_supported_atlas_azure_regions(self):
        self.assertEqual(
            resilience.atlas_azure_outage_filters(
                ["EUROPE_WEST", "US_EAST_2", "US_CENTRAL", "EUROPE_NORTH"]
            ),
            [
                {"cloudProvider": "AZURE", "regionName": "EUROPE_NORTH", "type": "REGION"},
                {"cloudProvider": "AZURE", "regionName": "EUROPE_WEST", "type": "REGION"},
                {"cloudProvider": "AZURE", "regionName": "US_CENTRAL", "type": "REGION"},
                {"cloudProvider": "AZURE", "regionName": "US_EAST_2", "type": "REGION"},
            ],
        )

    def test_accepts_comma_or_newline_separated_regions(self):
        expected = [
            {"cloudProvider": "AZURE", "regionName": "EUROPE_WEST", "type": "REGION"},
            {"cloudProvider": "AZURE", "regionName": "US_EAST_2", "type": "REGION"},
        ]
        self.assertEqual(
            resilience.atlas_azure_outage_filters("EUROPE_WEST,US_EAST_2"), expected
        )
        self.assertEqual(
            resilience.atlas_azure_outage_filters("EUROPE_WEST\nUS_EAST_2"), expected
        )

    def test_rejects_unknown_or_duplicate_regions(self):
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "supported Atlas Azure region"):
            resilience.atlas_azure_outage_filters(["EUROPE_WEST", "BRAZIL_SOUTH"], ["EUROPE_WEST"])
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "duplicate"):
            resilience.atlas_azure_outage_filters(["EUROPE_WEST", "europe_west"])


class AtlasProcessSummaryTests(unittest.TestCase):
    def setUp(self):
        self.processes = [
            {
                "hostname": "target-rs0-00.mongodb.net",
                "userAlias": "target-cluster-shard-00-00.mongodb.net",
                "replicaSetName": "target-rs0",
                "typeName": "REPLICA_PRIMARY",
            },
            {
                "hostname": "target-rs0-01.mongodb.net",
                "userAlias": "target-cluster-shard-00-01.mongodb.net",
                "replicaSetName": "target-rs0",
                "typeName": "REPLICA_SECONDARY",
            },
            {
                "hostname": "target-rs1-00.mongodb.net",
                "userAlias": "target-cluster-shard-01-00.mongodb.net",
                "replicaSetName": "target-rs1",
                "typeName": "SHARD_PRIMARY",
            },
            {
                "hostname": "target-rs1-01.mongodb.net",
                "userAlias": "target-cluster-shard-01-01.mongodb.net",
                "replicaSetName": "target-rs1",
                "typeName": "SHARD_SECONDARY",
            },
            {
                "hostname": "other-rs0-00.mongodb.net",
                "userAlias": "other-cluster-shard-00-00.mongodb.net",
                "replicaSetName": "other-rs0",
                "typeName": "REPLICA_PRIMARY",
            },
        ]

    def test_summarizes_only_target_cluster_replica_sets(self):
        result = resilience.atlas_cluster_process_summary(self.processes, "target-cluster")
        self.assertTrue(result["healthy"])
        self.assertEqual(result["processCount"], 4)
        self.assertEqual(result["replicaSetCount"], 2)
        self.assertEqual(
            result["primaryHosts"],
            ["target-rs0-00.mongodb.net", "target-rs1-00.mongodb.net"],
        )

    def test_detects_missing_primary_or_recovering_member(self):
        processes = [dict(item) for item in self.processes]
        processes[0]["typeName"] = "RECOVERING"
        result = resilience.atlas_cluster_process_summary(processes, "target-cluster")
        self.assertFalse(result["healthy"])
        self.assertEqual(result["primaryHosts"], ["target-rs1-00.mongodb.net"])
        self.assertEqual(result["unhealthyProcesses"], ["target-rs0-00.mongodb.net"])


class OutageClassificationTests(unittest.TestCase):
    def setUp(self):
        self.replication_specs = [
            {
                "regionConfigs": [
                    {
                        "providerName": "AZURE",
                        "regionName": "EUROPE_WEST",
                        "electableSpecs": {"nodeCount": 2},
                    },
                    {
                        "providerName": "AZURE",
                        "regionName": "US_CENTRAL",
                        "electableSpecs": {"nodeCount": 2},
                    },
                    {
                        "providerName": "AZURE",
                        "regionName": "US_EAST_2",
                        "electableSpecs": {"nodeCount": 1},
                    },
                ]
            }
        ]

    def test_classifies_minority_outage(self):
        result = resilience.atlas_classify_outage(
            self.replication_specs,
            [{"cloud_provider": "AZURE", "region_name": "US_EAST_2"}],
        )
        self.assertEqual(result["scope"], "minority")
        self.assertEqual(result["affectedElectableNodes"], 1)
        self.assertEqual(result["remainingElectableNodes"], 4)

    def test_classifies_majority_outage(self):
        result = resilience.atlas_classify_outage(
            self.replication_specs,
            [
                {"cloud_provider": "AZURE", "region_name": "EUROPE_WEST"},
                {"cloud_provider": "AZURE", "region_name": "US_CENTRAL"},
            ],
        )
        self.assertEqual(result["scope"], "majority")
        self.assertEqual(result["affectedElectableNodes"], 4)
        self.assertEqual(result["remainingElectableNodes"], 1)

    def test_reports_unknown_regions(self):
        result = resilience.atlas_classify_outage(
            self.replication_specs,
            [{"cloud_provider": "AZURE", "region_name": "EUROPE_NORTH"}],
        )
        self.assertEqual(
            result["unknownFilters"],
            [{"cloudProvider": "AZURE", "regionName": "EUROPE_NORTH", "type": "REGION"}],
        )

    def test_classifies_majority_per_replica_set(self):
        replication_specs = [
            {
                "id": "shard-0",
                "regionConfigs": [
                    {
                        "providerName": "AZURE",
                        "regionName": "EUROPE_WEST",
                        "electableSpecs": {"nodeCount": 2},
                    },
                    {
                        "providerName": "AZURE",
                        "regionName": "US_CENTRAL",
                        "electableSpecs": {"nodeCount": 1},
                    },
                ],
            },
            {
                "id": "shard-1",
                "regionConfigs": [
                    {
                        "providerName": "AZURE",
                        "regionName": "US_EAST_2",
                        "electableSpecs": {"nodeCount": 3},
                    },
                    {
                        "providerName": "AZURE",
                        "regionName": "EUROPE_NORTH",
                        "electableSpecs": {"nodeCount": 2},
                    },
                ],
            },
        ]
        result = resilience.atlas_classify_outage(
            replication_specs,
            [{"cloud_provider": "AZURE", "region_name": "EUROPE_WEST"}],
        )
        self.assertEqual(result["scope"], "majority")
        self.assertEqual(result["affectedElectableNodes"], 2)
        self.assertEqual(result["totalElectableNodes"], 8)
        self.assertEqual(result["replicationSpecImpacts"][0]["scope"], "majority")
        self.assertEqual(result["replicationSpecImpacts"][1]["scope"], "none")

    def test_rejects_losing_every_electable_node_in_one_replica_set(self):
        replication_specs = [
            {
                "regionConfigs": [
                    {
                        "providerName": "AZURE",
                        "regionName": "EUROPE_WEST",
                        "electableSpecs": {"nodeCount": 2},
                    }
                ]
            },
            {
                "regionConfigs": [
                    {
                        "providerName": "AZURE",
                        "regionName": "US_EAST_2",
                        "electableSpecs": {"nodeCount": 3},
                    }
                ]
            },
        ]
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "each replica set"):
            resilience.atlas_classify_outage(
                replication_specs,
                [{"cloud_provider": "AZURE", "region_name": "EUROPE_WEST"}],
            )

    def test_rejects_outage_of_all_electable_nodes(self):
        filters = [
            {"cloud_provider": "AZURE", "region_name": region}
            for region in ("EUROPE_WEST", "US_CENTRAL", "US_EAST_2")
        ]
        with self.assertRaisesRegex(resilience.AnsibleFilterError, "at least one electable node"):
            resilience.atlas_classify_outage(self.replication_specs, filters)


if __name__ == "__main__":
    unittest.main()
