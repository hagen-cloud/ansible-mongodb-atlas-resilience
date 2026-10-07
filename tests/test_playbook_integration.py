"""Exercise real playbooks against a loopback-only synthetic Atlas API."""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).parents[1]
PROJECT_ID = '0' * 24  # Synthetic fixture, never a real Atlas identifier.
TOKEN = 'synthetic-token-for-loopback-tests'


class MockAtlas(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(('127.0.0.1', 0), MockHandler)
        self.calls = []
        self.accepted_mutations = []
        self.failover = False
        self.fail_mutation = False
        self.freeze_primary = False
        self.outage = None
        self.outage_sequence = []
        self.auth_mode = 'bearer'
        self.regions = [('EUROPE_WEST', 2), ('US_EAST_2', 1), ('BRAZIL_SOUTH', 2)]


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self):
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.calls.append((self.command, path, body))
        if path == '/api/oauth/token':
            expected = 'Basic ' + base64.b64encode(b'synthetic-client:synthetic-secret').decode()
            if self.headers.get('Authorization') != expected:
                return self.reply(401, {})
            return self.reply(200, {'access_token': TOKEN})
        authorization = self.headers.get('Authorization', '')
        if self.server.auth_mode == 'digest':
            if not authorization.startswith('Digest '):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Digest realm="loopback", nonce="synthetic-nonce", qop="auth", algorithm=MD5')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        elif authorization != 'Bearer ' + TOKEN:
            return self.reply(401, {})
        if self.command in {'POST', 'DELETE'}:
            self.server.accepted_mutations.append((self.command, path, body))
        prefix = f'/api/atlas/v2/groups/{PROJECT_ID}'
        if path == '/api/atlas/v2/groups/byName/example-project':
            return self.reply(200, {'name': 'example-project', 'id': PROJECT_ID})
        if path == prefix + '/clusters/example-cluster':
            topology = [{'regionConfigs': [
                {'providerName': 'AZURE', 'regionName': region, 'electableSpecs': {'nodeCount': count}}
                for region, count in self.server.regions
            ]}]
            return self.reply(200, {'stateName': 'IDLE', 'effectiveReplicationSpecs': topology})
        if path == prefix + '/processes':
            primary = 1 if self.server.failover and not self.server.freeze_primary else 0
            processes = [
                {'hostname': f'fixture-{index}.mongodb.net',
                 'userAlias': f'example-cluster-shard-00-0{index}.mongodb.net',
                 'replicaSetName': 'fixture-rs0',
                 'typeName': 'REPLICA_PRIMARY' if index == primary else 'REPLICA_SECONDARY'}
                for index in range(3)
            ]
            return self.reply(200, {'results': processes})
        if path == prefix + '/events':
            return self.reply(200, {'totalCount': int(self.server.failover), 'results': []})
        if path == prefix + '/clusters/example-cluster/restartPrimaries':
            if self.command != 'POST':
                return self.reply(405, {})
            if self.server.fail_mutation:
                return self.reply(503, {})
            self.server.failover = True
            return self.reply(200, {})
        if path == prefix + '/clusters/example-cluster/outageSimulation':
            if self.command == 'POST':
                if self.server.fail_mutation:
                    return self.reply(503, {})
                self.server.outage = dict(json.loads(body), id='fixture-simulation', state='SIMULATING')
                return self.reply(200, self.server.outage)
            if self.command == 'DELETE':
                self.server.outage = None
                return self.reply(200, {})
            if self.server.outage_sequence:
                self.server.outage['state'] = self.server.outage_sequence.pop(0)
            if self.server.outage is None:
                return self.reply(404, {})
            return self.reply(200, self.server.outage)
        return self.reply(404, {})

    do_GET = dispatch
    do_POST = dispatch
    do_DELETE = dispatch


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook is required for integration tests')
class PlaybookIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = MockAtlas()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def run_playbook(self, playbook, *, success=True, credentials='token', check=False, **inputs):
        variables = {
            'atlas_base_url': f'http://127.0.0.1:{self.server.server_port}',
            'project_name': 'example-project', 'cluster_name': 'example-cluster',
            'confirmation': 'RUN_RESILIENCE_TEST',
            'atlas_poll_interval_seconds': 1, 'atlas_poll_retries': 1,
            'failover_event_poll_interval_seconds': 1, 'failover_event_poll_retries': 1,
            **inputs,
        }
        environment = dict(os.environ)
        # Never inherit the operator's real credentials or Ansible runner overrides.
        for key in list(environment):
            if key.startswith(('MONGODB_ATLAS_', 'ANSIBLE_')):
                environment.pop(key)
        environment.update(ANSIBLE_CONFIG=str(ROOT / 'ansible.cfg'), ANSIBLE_NOCOLOR='1')
        if credentials in {'token', 'both'}:
            environment['MONGODB_ATLAS_ACCESS_TOKEN'] = TOKEN
        if credentials in {'oauth', 'both'}:
            environment.update(MONGODB_ATLAS_CLIENT_ID='synthetic-client', MONGODB_ATLAS_CLIENT_SECRET='synthetic-secret')
        if credentials == 'digest':
            self.server.auth_mode = 'digest'
            environment.update(MONGODB_ATLAS_PUBLIC_KEY='synthetic-public', MONGODB_ATLAS_PRIVATE_KEY='synthetic-private')
        with tempfile.TemporaryDirectory(prefix='hc-atlas-test-') as temporary:
            vars_path = Path(temporary) / 'vars.json'
            vars_path.write_text(json.dumps(variables), encoding='utf-8')
            command = ['ansible-playbook', '-i', 'localhost,', playbook, '-e', '@' + str(vars_path)]
            if check:
                command.append('--check')
            result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, output)
            self.assertIn('CUSTOM STATS', output)
            self.assertIn('succeeded', output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        for secret in (TOKEN, 'synthetic-secret', 'synthetic-private'):
            self.assertNotIn(secret, output)
        return output

    def mutations(self):
        # Digest's initial 401 challenge is not an accepted mutation or a retry.
        return self.server.accepted_mutations

    def outage_fixture(self, region='US_EAST_2', state='SIMULATING'):
        self.server.outage = {
            'id': 'fixture-simulation', 'state': state,
            'outageFilters': [{'cloudProvider': 'AZURE', 'regionName': region, 'type': 'REGION'}],
            'expirationDate': '2099-01-01T00:00:00Z',
        }

    def test_failover_with_oauth_preserves_one_shot_and_recovery(self):
        self.run_playbook('playbooks/primary_failover.yml', credentials='oauth')
        self.assertTrue(self.server.failover)
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(self.server.calls[0][1], '/api/oauth/token')

    def test_preissued_token_takes_precedence(self):
        self.run_playbook('playbooks/primary_failover.yml', credentials='both')
        self.assertFalse(any(call[1] == '/api/oauth/token' for call in self.server.calls))

    def test_digest_authentication_is_independent_of_controller(self):
        self.run_playbook('playbooks/primary_failover.yml', credentials='digest')
        self.assertEqual(len(self.mutations()), 1)

    def test_complete_outage_start_and_repeated_cleanup(self):
        self.run_playbook('playbooks/regional_outage_start.yml', outage_regions=['BRAZIL_SOUTH'])
        self.assertEqual(self.server.outage['outageFilters'][0]['regionName'], 'BRAZIL_SOUTH')
        self.run_playbook('playbooks/regional_outage_end.yml', confirmation='END_OUTAGE_SIMULATION')
        self.assertIsNone(self.server.outage)
        self.run_playbook('playbooks/regional_outage_end.yml', confirmation='END_OUTAGE_SIMULATION')
        self.assertEqual([call[0] for call in self.mutations()], ['POST', 'DELETE'])

    def test_generic_entry_points_and_compatible_outage_reuse(self):
        self.outage_fixture()
        self.run_playbook('site.yml', resilience_test='regional_outage', outage_regions=['US_EAST_2'])
        self.assertEqual(self.mutations(), [])
        self.run_playbook('playbooks/regional_outage.yml', outage_state='absent', confirmation='END_OUTAGE_SIMULATION')
        self.assertEqual([call[0] for call in self.mutations()], ['DELETE'])

    def test_majority_guard_blocks_before_start(self):
        self.run_playbook('playbooks/regional_outage_start.yml', success=False, outage_regions=['EUROPE_WEST', 'BRAZIL_SOUTH'])
        self.assertEqual(self.mutations(), [])

    def test_majority_opt_in_preserves_classification(self):
        output = self.run_playbook('playbooks/regional_outage_start.yml', outage_regions=['EUROPE_WEST', 'BRAZIL_SOUTH'], allow_majority_outage=True)
        self.assertIn('majority', output)
        self.assertEqual(len(self.mutations()), 1)

    def test_unknown_topology_region_and_allowlist_block_before_start(self):
        for variables in (
            {'outage_regions': ['UNKNOWN_REGION']},
            {'outage_regions': ['BRAZIL_SOUTH'], 'atlas_allowed_outage_regions': ['EUROPE_WEST']},
            {'outage_regions': ['EUROPE_WEST', 'US_EAST_2', 'BRAZIL_SOUTH'], 'allow_majority_outage': True},
        ):
            with self.subTest(variables=variables):
                self.run_playbook('playbooks/regional_outage_start.yml', success=False, **variables)
                self.assertEqual(self.mutations(), [])

    def test_confirmation_and_check_mode_fail_before_authentication(self):
        for variables in ({'confirmation': ''}, {'check': True}):
            with self.subTest(variables=variables):
                self.run_playbook('playbooks/primary_failover.yml', success=False, **variables)
                self.assertEqual(self.server.calls, [])

    def test_failed_start_request_is_not_retried(self):
        self.server.fail_mutation = True
        self.run_playbook('playbooks/regional_outage_start.yml', success=False, outage_regions=['US_EAST_2'])
        self.assertEqual(len(self.mutations()), 1)

    def test_failover_requires_changed_primary_after_polling(self):
        self.server.freeze_primary = True
        self.run_playbook('playbooks/primary_failover.yml', success=False)
        self.assertEqual(len(self.mutations()), 1)

    def test_cleanup_waits_for_starting_and_rejects_failed_state(self):
        self.outage_fixture(state='STARTING')
        self.server.outage_sequence = ['STARTING', 'SIMULATING']
        self.run_playbook('playbooks/regional_outage_end.yml', confirmation='END_OUTAGE_SIMULATION')
        self.assertEqual([call[0] for call in self.mutations()], ['DELETE'])
        self.server.calls.clear()
        self.server.accepted_mutations.clear()
        self.outage_fixture(state='FAILED')
        self.run_playbook('playbooks/regional_outage_end.yml', success=False, confirmation='END_OUTAGE_SIMULATION')
        self.assertEqual(self.mutations(), [])


if __name__ == '__main__':
    unittest.main()
