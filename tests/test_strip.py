import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from devtool_core.strip_artifacts import strip_tree,loaded_identity


class StripTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('strip'),'requires host C compiler and strip')
    def test_real_elf_debug_strip_preserves_mapped_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();code=root/'main.c';code.write_text('int main(void){return 0;}\n')
            binary=source/'app';subprocess.run(['cc','-g','-o',str(binary),str(code)],check=True)
            original=binary.read_bytes();identity=loaded_identity(binary)
            (source/'link').symlink_to('app')
            dest=root/'release';report=strip_tree(source,dest)
            self.assertEqual(len(report['elf']),1)
            self.assertLess((dest/'app').stat().st_size,len(original))
            self.assertEqual(loaded_identity(dest/'app'),identity)
            self.assertEqual(binary.read_bytes(),original)
            self.assertEqual((dest/'link').readlink(),Path('app'))
            subprocess.run([str(dest/'app')],check=True)
