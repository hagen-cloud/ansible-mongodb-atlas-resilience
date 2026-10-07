import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_entry_points_run_locally_without_facts(self):
        for relative_path in (
            "site.yml",
            "playbooks/primary_failover.yml",
            "playbooks/regional_outage.yml",
            "playbooks/regional_outage_start.yml",
            "playbooks/regional_outage_end.yml",
        ):
            playbook = yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))
            self.assertEqual(playbook[0]["hosts"], "localhost")
            self.assertFalse(playbook[0]["gather_facts"])

    def test_project_id_is_resolved_from_project_name(self):
        resolver = (ROOT / "roles/mongodb_atlas_resilience/tasks/resolve_project.yml").read_text(
            encoding="utf-8"
        )
        validation = (ROOT / "roles/mongodb_atlas_resilience/tasks/validate_inputs.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("groups/byName", resolver)
        self.assertIn("project_name", validation)
        self.assertNotIn("24-character hexadecimal", validation)

    def test_input_contract_uses_names_and_region_policy(self):
        content = (ROOT / "docs/input-contract.md").read_text(encoding="utf-8")
        self.assertIn("project_name", content)
        self.assertIn("cluster_name", content)
        self.assertIn("atlas_allowed_outage_regions", content)
        self.assertIn("topology", content)

    def test_documentation_does_not_require_aks_or_mongosh(self):
        for relative_path in ("README.md", "docs/input-contract.md", "docs/execution-runbook.md"):
            content = (ROOT / relative_path).read_text(encoding="utf-8").lower()
            self.assertNotIn("aks", content, relative_path)
            self.assertNotIn("mongosh", content, relative_path)

    def test_primary_failover_uses_atlas_api_not_database_stepdown(self):
        content = (ROOT / "roles/mongodb_atlas_resilience/tasks/primary_failover.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("restartPrimaries", content)
        self.assertNotIn("replSetStepDown", content)
        self.assertIn("CLUSTER_UPDATE_COMPLETED", content)
        self.assertNotIn("eventType=PRIMARY_ELECTED", content)
        self.assertIn("atlas_cluster_process_summary", content)

    def test_outage_lifecycle_has_start_status_and_idempotent_cleanup(self):
        start = (ROOT / "roles/mongodb_atlas_resilience/tasks/regional_outage_started.yml").read_text(
            encoding="utf-8"
        )
        cleanup = (ROOT / "roles/mongodb_atlas_resilience/tasks/regional_outage_absent.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("outageSimulation", start)
        self.assertIn('method: POST', start)
        self.assertIn('method: DELETE', cleanup)
        self.assertIn('404', cleanup)

    def test_environment_api_key_credentials_are_supported(self):
        defaults = (ROOT / "roles/mongodb_atlas_resilience/defaults/main.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("MONGODB_ATLAS_PUBLIC_KEY", defaults)
        self.assertIn("MONGODB_ATLAS_PRIVATE_KEY", defaults)

        task_root = ROOT / "roles/mongodb_atlas_resilience/tasks"
        for task_file in task_root.glob("*.yml"):
            documents = yaml.safe_load(task_file.read_text(encoding="utf-8")) or []
            for task in documents:
                uri = task.get("ansible.builtin.uri", {})
                if uri.get("headers") == "{{ atlas_headers }}":
                    self.assertIn("url_username", uri, f"{task_file.name}: {task.get('name')}")
                    self.assertIn("url_password", uri, f"{task_file.name}: {task.get('name')}")

    def test_authorized_uri_tasks_are_protected_by_no_log(self):
        task_root = ROOT / "roles/mongodb_atlas_resilience/tasks"
        for task_file in task_root.glob("*.yml"):
            documents = yaml.safe_load(task_file.read_text(encoding="utf-8")) or []
            for task in documents:
                uri = task.get("ansible.builtin.uri")
                if uri and (uri.get("headers") or uri.get("url_username")):
                    self.assertTrue(task.get("no_log"), f"{task_file.name}: {task.get('name')}")

    def test_polling_tasks_fail_when_retries_are_exhausted(self):
        task_root = ROOT / "roles/mongodb_atlas_resilience/tasks"
        for task_file in task_root.glob("*.yml"):
            documents = yaml.safe_load(task_file.read_text(encoding="utf-8")) or []
            for task in documents:
                if "until" in task:
                    self.assertNotIn("failed_when", task, f"{task_file.name}: {task.get('name')}")

    def test_mutating_requests_are_not_retried(self):
        task_root = ROOT / "roles/mongodb_atlas_resilience/tasks"
        for task_file in task_root.glob("*.yml"):
            documents = yaml.safe_load(task_file.read_text(encoding="utf-8")) or []
            for task in documents:
                uri = task.get("ansible.builtin.uri", {})
                if uri.get("method") in {"POST", "DELETE"}:
                    self.assertNotIn("retries", task, f"{task_file.name}: {task.get('name')}")

    def test_no_literal_credentials_are_committed(self):
        forbidden = ("client" + "_secret: mongodb", "Bearer " + "eyJ", "BEGIN " + "PRIVATE KEY")
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and path.suffix not in {".pyc"}:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for marker in forbidden:
                    self.assertNotIn(marker, content, str(path))


if __name__ == "__main__":
    unittest.main()
