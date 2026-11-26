import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from devtool_core.config import read_project
from devtool_core.planner import make_plan
from devtool_core.runtime import external_environment, helper_command, internal_main
from devtool_core.model import Target
from devtool_core import transport


class RuntimeTests(unittest.TestCase):
    def test_frozen_helper_and_environment(self):
        with patch.object(sys,'frozen',True,create=True), patch.object(sys,'executable','/opt/tools/devtool'):
            self.assertEqual(helper_command('transport'),('/opt/tools/devtool','_internal','transport'))
            env=external_environment({'LD_LIBRARY_PATH':'/bundle','LD_LIBRARY_PATH_ORIG':'/original','OTHER':'yes'},executable='/opt/tools/devtool')
            self.assertEqual(env['LD_LIBRARY_PATH'],'/original')
            self.assertNotIn('LD_LIBRARY_PATH_ORIG',env)
            self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'],'1')
            self.assertNotIn('LD_LIBRARY_PATH',external_environment({'LD_LIBRARY_PATH':'/bundle'},executable='/usr/bin/git'))
        self.assertEqual(helper_command('transport')[1:],('-m','devtool_core.transport'))

    def test_frozen_transfer_plan_uses_binary_on_both_ends(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'devtool.toml';config.write_text('''[targets.lab]
kind="ssh"
host="dev@example.invalid"
workdir="/srv/demo"
[tasks.stage]
transfers=[{kind="rsync",target="lab",source="dist",destination="stage/app"}]
''')
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable','/opt/devtool'):
                step=make_plan(read_project(config),'stage').steps[0]
                self.assertEqual(step.argv[:4],('/opt/devtool','_internal','transport','rsync'))
                self.assertEqual(step.argv[step.argv.index('--engine')+1],'./devtool')
        target=Target('lab','ssh','/srv/demo','dev@example.invalid',engine='/opt/devtool')
        with patch.object(transport,'remote') as remote:
            transport.remote_helper(target,['verify-tree','--path','/srv/demo/stage','--sha256','a'*64])
            self.assertEqual(remote.call_args.args[1][:3],['/opt/devtool','_internal','transport'])
