import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from devtool_core.artifacts.fetch import fetch_file
from devtool_core.delivery.bundles import archive_tags
from devtool_core.artifacts.archive import file_info
from devtool_core.model import DevtoolError


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def test_verified_fetch_repairs_only_after_valid_download(self):
        original=self.root/'original';original.write_bytes(b'good');output=self.root/'cache/package'
        digest=hashlib.sha256(b'good').hexdigest()
        self.assertFalse(fetch_file(original.as_uri(),output,digest,4)['cached'])
        with patch('devtool_core.artifacts.fetch.urlopen',side_effect=AssertionError('cache should be reused')):
            self.assertTrue(fetch_file(original.as_uri(),output,digest)['cached'])
        output.write_bytes(b'corrupt');original.write_bytes(b'bad')
        with self.assertRaises(DevtoolError):fetch_file(original.as_uri(),output,digest)
        self.assertEqual(output.read_bytes(),b'corrupt')
        original.write_bytes(b'good');fetch_file(original.as_uri(),output,digest)
        self.assertEqual(output.read_bytes(),b'good')

    def test_full_docker_archive_requires_matching_tag_and_identity(self):
        archive=self.root/'images.tar';config=b'{"architecture":"amd64"}';digest=hashlib.sha256(config).hexdigest()
        files={'config.json':config,'manifest.json':json.dumps([{'Config':'config.json','Layers':[],'RepoTags':['example.invalid/app:1']}]).encode()}
        with tarfile.open(archive,'w') as out:
            for name,data in files.items():out.addfile(file_info(name,0o644,len(data)),io.BytesIO(data))
        archive_tags(archive,{'example.invalid/app:1':'sha256:'+digest+' linux/amd64'})
        with self.assertRaises(DevtoolError):archive_tags(archive,{'example.invalid/app:2':'sha256:'+digest+' linux/amd64'})
        with self.assertRaises(DevtoolError):archive_tags(archive,{'example.invalid/app:1':'sha256:'+'f'*64+' linux/amd64'})
