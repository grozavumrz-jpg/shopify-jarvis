"""Deploy identity must identify the actual Render revision, without inventing one locally."""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from main import app
from starlette.testclient import TestClient

class DeployIdentityTest(unittest.TestCase):
    def test_health_reports_runtime_revision_and_handles_absence(self):
        client = TestClient(app)
        with patch.dict(os.environ, {'RENDER_GIT_COMMIT': 'abc1234'}):
            self.assertEqual(client.get('/health').json()['deploy_commit'], 'abc1234')
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(client.get('/health').json()['deploy_commit'])
