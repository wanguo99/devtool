import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from devtool_core.config import read_project
from devtool_core.model import DevtoolError
from devtool_core.planner import make_plan, action_task
from devtool_core.sources import prepare_source, source_tasks


def git(cwd,*args):
    return subprocess.check_output(['git','-C',str(cwd),*args],text=True,stderr=subprocess.DEVNULL).strip()


class SourceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.base=Path(t.name);self.root=self.base/'project';self.root.mkdir()
        self.origin=self.base/'origin';self.origin.mkdir();git(self.origin,'init','--initial-branch=main')
        git(self.origin,'config','user.name','Fixture');git(self.origin,'config','user.email','fixture@example.invalid');git(self.origin,'config','commit.gpgsign','false')
        (self.origin/'app').write_text('one');git(self.origin,'add','app');git(self.origin,'commit','-m','one')
        self.first=git(self.origin,'rev-parse','HEAD')
        env=patch.dict(os.environ,{'GIT_ALLOW_PROTOCOL':'file'});env.start();self.addCleanup(env.stop)

    def test_declarative_source_group_default_exclusion(self):
        cfg=self.root/'devtool.toml';cfg.write_text('''[sources.radio]
url="https://example.invalid/radio.git"
groups=["ran"]
branch="main"
[sources.old]
url="https://example.invalid/old.git"
groups=["legacy"]
default=false
''')
        project=read_project(cfg)
        self.assertEqual(make_plan(project,action_task(project,'clone')).tasks,('source.clone.radio','clone.all'))
        self.assertEqual(make_plan(project,action_task(project,'clone','legacy')).tasks,('source.clone.old','clone.legacy'))
        self.assertFalse((self.root/'source').exists())
        self.assertIn('sources',make_plan(project,'clone.all').steps[0].argv[2])

    def test_real_clone_fetch_preserves_dirty_head(self):
        dest=self.root/'source/app';url=str(self.origin)
        prepare_source('clone',self.root,'source/app',url,branch='main')
        (dest/'app').write_text('local uncommitted')
        (self.origin/'app').write_text('two');git(self.origin,'add','app');git(self.origin,'commit','-m','two')
        second=git(self.origin,'rev-parse','HEAD')
        prepare_source('clone',self.root,'source/app',url,branch='main')
        self.assertEqual(git(dest,'rev-parse','origin/main'),self.first)
        prepare_source('update',self.root,'source/app',url,branch='main')
        self.assertEqual(git(dest,'rev-parse','origin/main'),second)
        self.assertEqual(git(dest,'rev-parse','HEAD'),self.first)
        self.assertEqual((dest/'app').read_text(),'local uncommitted')
        with self.assertRaisesRegex(DevtoolError,'origin mismatch'):
            prepare_source('clone',self.root,'source/app',str(self.base/'other'))

    def test_pinned_revision_and_path_overlap(self):
        prepare_source('clone',self.root,'pinned',str(self.origin),revision=self.first)
        self.assertEqual(git(self.root/'pinned','rev-parse','HEAD'),self.first)
        self.assertEqual(git(self.root/'pinned','rev-parse','--abbrev-ref','HEAD'),'HEAD')
        with self.assertRaisesRegex(DevtoolError,'overlap'):
            source_tasks({'x':{'url':'x','path':'a'},'y':{'url':'y','path':'a/b'}},self.root)
        for path in ('../other','/tmp/bad','.git'):
            with self.assertRaises(DevtoolError): prepare_source('clone',self.root,path,str(self.origin))

    def test_submodules_initialize_missing_without_resetting_existing(self):
        child=self.base/'child';child.mkdir();git(child,'init','--initial-branch=main')
        git(child,'config','user.name','Fixture');git(child,'config','user.email','fixture@example.invalid');git(child,'config','commit.gpgsign','false')
        (child/'child.txt').write_text('original');git(child,'add','child.txt');git(child,'commit','-m','child')
        git(self.origin,'submodule','add',str(child),'vendor/child');git(self.origin,'commit','-am','submodule')
        prepare_source('clone',self.root,'with-submodule',str(self.origin),submodules=True)
        checkout=self.root/'with-submodule/vendor/child';self.assertTrue((checkout/'child.txt').exists())
        head=git(checkout,'rev-parse','HEAD');(checkout/'child.txt').write_text('dirty')
        prepare_source('update',self.root,'with-submodule',str(self.origin),submodules=True)
        self.assertEqual(git(checkout,'rev-parse','HEAD'),head)
        self.assertEqual((checkout/'child.txt').read_text(),'dirty')
