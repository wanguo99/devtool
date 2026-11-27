import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from devtool_core.artifacts.archive import pack_directory, unpack_directory, file_info
from devtool_core.config import read_project
from devtool_core.model import DevtoolError, Target
from devtool_core.planning.planner import make_plan
from devtool_core.delivery import oci, oci_layout, rsync
from devtool_core.artifacts.tree import tree_identity


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(obj):
    return json.dumps(obj,sort_keys=True).encode()


def tar_fixture(path, files):
    with tarfile.open(path,'w') as archive:
        for name, data in files.items():
            archive.addfile(file_info(name,0o644,len(data)),io.BytesIO(data))


def oci_fixture(path, image='example.invalid/app:one', layer=b'layer1', extra_tag=False):
    files={}
    def blob(value):
        name='blobs/sha256/'+digest(value)
        files[name]=value
        return {'digest':'sha256:'+digest(value),'size':len(value)},name
    config, config_path=blob(encoded({'architecture':'amd64','os':'linux'}))
    first, first_path=blob(b'shared immutable base')
    last, last_path=blob(layer)
    descriptor, _=blob(encoded({'schemaVersion':2,'config':config,'layers':[first,last]}))
    descriptor['annotations']={'io.containerd.image.name':image}
    files['index.json']=encoded({'schemaVersion':2,'manifests':[descriptor]})
    files['oci-layout']=encoded({'imageLayoutVersion':'1.0.0'})
    files['manifest.json']=encoded([{'Config':config_path,'Layers':[first_path,last_path], 'RepoTags':[image]+(['unexpected:tag'] if extra_tag else [])}])
    tar_fixture(path,files)
    return descriptor['digest']+' linux/amd64', files


class PortableTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); self.root=Path(td.name)

    def test_archive_round_trip_permissions_and_links(self):
        source=self.root/'src'; source.mkdir(); (source/'sub').mkdir(); app=source/'sub/app'; app.write_text('hello'); app.chmod(0o755)
        (source/'shortcut').symlink_to('sub/app')
        packed=self.root/'bundle.tar.gz'
        expected=pack_directory(source,packed)
        other=self.root/'again.tar.gz'; pack_directory(source,other)
        self.assertEqual(packed.read_bytes(),other.read_bytes())
        dest=self.root/'restored'; actual=unpack_directory(packed,dest)
        self.assertEqual(actual,expected); self.assertEqual((dest/'sub/app').stat().st_mode&0o777,0o755)
        self.assertEqual(tree_identity(dest)['sha256'],tree_identity(source)['sha256'])
        with self.assertRaises(DevtoolError): unpack_directory(packed,dest)
        with self.assertRaises(DevtoolError): pack_directory(source,packed)

    def test_archive_rejects_unsafe_paths_and_tampered_manifest(self):
        bad=self.root/'bad.tar'
        tar_fixture(bad,{'../escaped':b'bad'})
        with self.assertRaises(DevtoolError): unpack_directory(bad,self.root/'destination')
        self.assertFalse((self.root/'destination').exists()); self.assertFalse((self.root.parent/'escaped').exists())
        source=self.root/'src'; source.mkdir(); (source/'f').write_text('original'); packed=self.root/'bundle.tar.gz'
        pack_directory(source,packed)
        tampered=self.root/'tampered.tar'
        with tarfile.open(packed,'r:*') as original, tarfile.open(tampered,'w') as altered:
            for member in original:
                if member.name=='payload/f': altered.addfile(member,io.BytesIO(b'tampered'))
                else: altered.addfile(member,original.extractfile(member) if member.isfile() else None)
        with self.assertRaisesRegex(DevtoolError,'does not match'): unpack_directory(tampered,self.root/'destination')
        self.assertFalse((self.root/'destination').exists())

    def test_export_rejects_nonportable_member_name(self):
        source=self.root/'source';source.mkdir();(source/'name\\with-backslash').write_text('fixture')
        bundle=self.root/'bundle.tar.gz'
        with self.assertRaisesRegex(DevtoolError,'unsafe archive path'):
            pack_directory(source,bundle)
        self.assertFalse(bundle.exists())

    def test_archive_and_oci_plans(self):
        config=self.root/'devtool.toml'; config.write_text('''schema=1
[project]
name="demo"
[targets.lab]
kind="ssh"
host="dev@example.invalid"
workdir="/srv/app"
[tasks."export.all"]
transfers=[{kind="archive-pack",source="dist",destination="bundle.tar.gz"}]
[tasks."import.all"]
transfers=[{kind="archive-unpack",source="bundle.tar.gz",destination="restored"}]
[tasks."stage.image"]
transfers=[{kind="oci-delta",target="lab",image="example.invalid/app:one",destination="cache/oci"}]
''')
        project=read_project(config)
        self.assertEqual(make_plan(project,'export.all').steps[0].argv[3],'archive-pack')
        self.assertEqual(make_plan(project,'import.all').steps[0].argv[3],'archive-unpack')
        self.assertEqual(make_plan(project,'stage.image').steps[0].tools,('ssh','rsync','docker'))
        self.assertFalse((self.root/'bundle.tar.gz').exists())

    def test_oci_incremental_staging_and_reconstruction(self):
        if not shutil.which('rsync'): self.skipTest('rsync not installed')
        archive=self.root/'first.tar'; first, _=oci_fixture(archive)
        cache=self.root/'cache'; cache.mkdir(); staged=self.root/'staged1'
        first_manifest=oci_layout.stage_archive(archive,staged,'example.invalid/app:one',first)
        def sync(folder):
            return subprocess.run([*rsync.rsync_options(),'--itemize-changes','--',str(folder)+'/',str(cache)+'/'],check=True,capture_output=True,text=True).stdout
        sync(staged)
        next_archive=self.root/'next.tar'; second, files=oci_fixture(next_archive,image='example.invalid/app:two',layer=b'changed')
        staged2=self.root/'staged2'; second_manifest=oci_layout.stage_archive(next_archive,staged2,'example.invalid/app:two',second)
        shared={m['path'] for m in first_manifest['entries']}&{m['path'] for m in second_manifest['entries']}
        self.assertIn('blobs/sha256/'+digest(b'shared immutable base'),shared)
        report=sync(staged2)
        self.assertFalse(any(digest(b'shared immutable base') in line for line in report.splitlines() if line.startswith('>f')))
        output=self.root/'reconstructed.tar'; oci_layout.reconstruct(cache,output,oci_layout.identity_digest(second_manifest))
        with tarfile.open(output,'r:') as rebuilt:
            self.assertEqual({m.name:rebuilt.extractfile(m).read() for m in rebuilt if m.isfile()},files)
        self.assertTrue((cache/'payload'/'blobs/sha256'/digest(b'layer1')).is_file())
        (cache/'payload'/'blobs/sha256'/digest(b'changed')).write_bytes(b'xxxxxxx')
        with self.assertRaisesRegex(DevtoolError,'integrity mismatch'):
            oci_layout.reconstruct(cache,self.root/'failed.tar',oci_layout.identity_digest(second_manifest))

    def test_oci_tag_and_identity_mismatch(self):
        archive=self.root/'bad.tar'; expected,_=oci_fixture(archive,extra_tag=True)
        with self.assertRaisesRegex(DevtoolError,'unexpected image tags'):
            oci_layout.stage_archive(archive,self.root/'bad','example.invalid/app:one',expected)
        archive=self.root/'good.tar'; expected,_=oci_fixture(archive)
        with self.assertRaisesRegex(DevtoolError,'candidate ID'):
            oci_layout.stage_archive(archive,self.root/'wrong','example.invalid/app:one','sha256:'+'f'*64+' linux/amd64')
        good=self.root/'good'; manifest=oci_layout.stage_archive(archive,good,'example.invalid/app:one',expected)
        with patch.object(oci,'docker_identity',return_value='sha256:'+'f'*64+' linux/amd64'),patch.object(oci,'run_checked') as call:
            with self.assertRaisesRegex(DevtoolError,'already refers'):
                oci.load_candidate(good,oci_layout.identity_digest(manifest))
            call.assert_not_called()
        with patch.object(oci,'docker_identity',side_effect=[None,expected]),patch.object(oci,'run_checked') as call:
            oci.load_candidate(good,oci_layout.identity_digest(manifest)); self.assertEqual(call.call_args.args[0][:3],['docker','image','load'])

    def test_oci_existing_candidate_skips_transfer(self):
        target=Target('lab','ssh','/srv/demo','dev@example.invalid')
        expected='sha256:'+'a'*64+' linux/arm64'
        with patch.object(oci,'docker_identity',return_value=expected),patch.object(oci,'run_checked') as call,patch.object(oci,'remote_helper') as remote:
            oci.send_candidate(target,'example.invalid/app:one','cache/images')
            call.assert_not_called(); remote.assert_not_called()
