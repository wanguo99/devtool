import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from devtool_core.artifacts.manifest import create_manifest, verify_manifest
from devtool_core.model import DevtoolError


class ManifestTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.root=Path(d.name);(self.root/'dist').mkdir();(self.root/'dist/app').write_text('fixture')

    def test_files_and_images_produce_immutable_manifest(self):
        image='example.invalid/app:v1';identity='sha256:'+'a'*64+' linux/arm64'
        with patch('devtool_core.artifacts.manifest.docker_identity',return_value=identity):
            manifest=create_manifest(self.root,'release.json',['dist'],[image])
            self.assertEqual(verify_manifest(self.root,'release.json')['sha256'],manifest['sha256'])
        with self.assertRaisesRegex(DevtoolError,'already exists'):
            create_manifest(self.root,'release.json',['dist'])
        with patch('devtool_core.artifacts.manifest.docker_identity',return_value='sha256:'+'b'*64+' linux/arm64'):
            with self.assertRaisesRegex(DevtoolError,'image differs'): verify_manifest(self.root,'release.json')
        (self.root/'dist/app').write_text('changed')
        with self.assertRaisesRegex(DevtoolError,'artifact differs'): verify_manifest(self.root,'release.json')

    def test_reject_manifest_inside_payload_or_path_escape(self):
        for name in ('dist/manifest.json','../manifest.json','/tmp/manifest.json'):
            with self.assertRaises(DevtoolError): create_manifest(self.root,name,['dist'])

    def test_declarative_manifest_blocks_deploy_on_modified_artifact(self):
        import contextlib,io,sys
        from devtool_core.config import read_project
        from devtool_core.planning.planner import make_plan
        from devtool_core.execution.runner import execute
        config=self.root/'devtool.toml'
        config.write_text('''[tasks.build]
commands=[["%s", "-c", "from pathlib import Path; Path('dist/app').write_text('new')"]]
artifacts=["dist/app"]
manifest="candidate.json"
[tasks.deploy]
requires=["dist/app"]
verify_manifests=["candidate.json"]
commands=[["%s","-c","from pathlib import Path; Path('activated').touch()"]]
'''%(sys.executable,sys.executable))
        project=read_project(config)
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(execute(make_plan(project,'build'),state_root=self.root/'state'),0)
            self.assertTrue((self.root/'candidate.json').is_file())
            (self.root/'dist/app').write_text('tampered')
            self.assertNotEqual(execute(make_plan(project,'deploy'),state_root=self.root/'state'),0)
        self.assertFalse((self.root/'activated').exists())
