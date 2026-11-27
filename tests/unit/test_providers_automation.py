import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from devtool_core.cli import main
from devtool_core.config import read_project
from devtool_core.model import DevtoolError
from devtool_core.planning.planner import make_plan


class ProvidersAutomation(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.root=self.base/'project';self.root.mkdir()
        self.config=self.root/'devtool.toml'
        env=patch.dict(os.environ,{'DEVTOOL_STATE_HOME':str(self.base/'state')});env.start();self.addCleanup(env.stop)

    def write_provider(self,source,extra=''):
        self.config.write_text('schema=1\nproviders=["provider.py"]\n[project]\nname="demo"\n'+extra)
        (self.root/'provider.py').write_text(source)

    def call(self,*args):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=main(['--project',str(self.root),*args])
        return code,out.getvalue(),err.getvalue()

    def test_provider_requires_explicit_opt_in(self):
        self.write_provider('from pathlib import Path\nPath(__file__).with_name("loaded").touch()\ndef provide(context):\n return {"tasks":{"build.all":{"commands":[["true"]]}}}\n')
        with self.assertRaisesRegex(DevtoolError,'allow-providers'):
            read_project(self.config)
        self.assertFalse((self.root/'loaded').exists())
        project=read_project(self.config,allow_providers=True)
        self.assertTrue((self.root/'loaded').exists())
        self.assertEqual(make_plan(project,'build.all').steps[0].argv,('true',))

    def test_provider_validation_and_duplicate_names(self):
        self.write_provider('def provide(context):\n return {"tasks":{"build.all":{"commands":[["true"]]}}}\n', '[tasks."build.all"]\ncommands=[["echo","original"]]')
        with self.assertRaisesRegex(DevtoolError,'duplicates'):
            read_project(self.config,allow_providers=True)
        self.write_provider('def provide(context):\n return {"tasks":{"broken":{"dependencies":["missing"]}}}\n')
        with self.assertRaisesRegex(DevtoolError,'unknown task'):
            read_project(self.config,allow_providers=True)
        self.config.write_text('schema=1\nproviders=["../outside.py"]\n[project]\nname="demo"')
        (self.base/'outside.py').write_text('raise RuntimeError("must not run")')
        with self.assertRaisesRegex(DevtoolError,'invalid provider path'):
            read_project(self.config,allow_providers=True)

    def test_provider_plan_is_pure_for_pure_provider(self):
        self.write_provider('def provide(context):\n return {"tasks":{"build.all":{"commands":[["echo",context.project]]}}}\n')
        before=set(self.root.iterdir())
        code,out,_=self.call('--allow-providers','plan','build')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['steps'][0]['argv'],['echo','demo'])
        self.assertEqual(set(self.root.iterdir()),before)
        self.assertFalse((self.base/'state').exists())

    def test_direct_execution_without_config_and_machine_readable_output(self):
        code,out,err=self.call('exec','--json','--',sys.executable,'-c','print("child output")')
        self.assertEqual(code,0)
        record=json.loads(out);self.assertEqual(record['status'],'SUCCEEDED')
        self.assertIn('child output',err)
        self.assertEqual(record['plan']['project'],'adhoc')
        code,out,_=self.call('history','--limit','1');self.assertEqual(code,0)
        self.assertEqual(json.loads(out)[0]['id'],record['id'])
        code,out,_=self.call('show',record['id']);self.assertEqual(json.loads(out)['status'],'SUCCEEDED')

    def test_failed_json_operation_and_plan_exec(self):
        code,out,_=self.call('plan','exec','--',sys.executable,'-c','raise SystemExit(6)')
        self.assertEqual(code,0);self.assertFalse((self.base/'state').exists())
        code,out,_=self.call('exec','--json','--',sys.executable,'-c','raise SystemExit(6)')
        self.assertEqual(code,6);self.assertEqual(json.loads(out)['status'],'FAILED')

    def test_history_and_direct_execution_do_not_load_providers(self):
        self.write_provider('raise RuntimeError("do not load for history")')
        code,out,_=self.call('exec','--json','--',sys.executable,'-c','pass')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['plan']['project'],'demo')
        self.assertEqual(self.call('history')[0],0)

    def test_list_and_validate_json(self):
        self.config.write_text('schema=1\n[project]\nname="demo"\n[tasks."test.all"]\ncommands=[["true"]]\n')
        for args in (('list','--json'),('validate',)):
            code,out,_=self.call(*args);self.assertEqual(code,0)
            self.assertEqual(json.loads(out)['tasks'][0]['name'],'test.all')
