"""Prevent infrastructure dependencies from creeping back into the core."""
import ast
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "devtool_core"


class ArchitectureTests(unittest.TestCase):
    def test_layer_dependencies(self):
        # Each implementation area may depend only on these other areas.
        # The root entry-point shims are intentionally outside this check.
        allowed = {
            "runtime": {"model"},
            "sources": {"model", "runtime"},
            "artifacts": {"model", "runtime"},
            "delivery": {"model", "runtime", "artifacts"},
            "planning": {"model", "runtime", "delivery"},
            "config": {"model", "planning", "sources"},
            "execution": {"model", "runtime", "artifacts"},
            "cli": {"model", "runtime", "config", "planning", "execution", "artifacts", "delivery", "sources"},
        }
        for path in PACKAGE.glob("*/*.py"):
            area = path.parent.name
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        module = importlib.util.resolve_name(
                            "." * node.level + module, f"devtool_core.{area}")
                    names = [module]
                elif isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                else:
                    continue
                for name in names:
                    if not name.startswith("devtool_core."):
                        continue
                    dependency = name.split(".")[1]
                    with self.subTest(module=str(path.relative_to(PACKAGE)), dependency=name):
                        self.assertIn(dependency, allowed[area] | {area})

    def test_local_plan_does_not_load_optional_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "devtool.toml"
            config.write_text('[commands]\nstatus=["echo","ready"]\n')
            script = """
from devtool_core.cli import main
import json, sys
code = main(["--project", sys.argv[1], "plan", "status"])
assert code == 0
print(json.dumps(sorted(sys.modules)))
"""
            output = subprocess.check_output(
                [sys.executable, "-c", script, str(config)], text=True)
            modules = json.loads(output.splitlines()[-1])
            for prefix in ("devtool_core.delivery", "devtool_core.sources.git",
                           "devtool_core.runtime.docker", "devtool_core.runtime.targets",
                           "devtool_core.artifacts.archive"):
                self.assertFalse(any(name == prefix or name.startswith(prefix + ".")
                                     for name in modules), prefix)

    def test_source_helper_module_names_remain_usable(self):
        for name in ("transport", "manifest", "sources"):
            result = subprocess.run(
                [sys.executable, "-m", f"devtool_core.{name}", "--help"],
                capture_output=True, text=True)
            with self.subTest(helper=name):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)
        # Existing source-mode transports still call this exact module path.
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, "-m", "devtool_core.transport",
                            "prepare-tree", "--root", directory, "--destination", "stage"],
                           check=True, capture_output=True)
            self.assertTrue((pathlib.Path(directory) / "stage").is_dir())

    def test_cli_entry_point_remains_callable_after_loading_implementation(self):
        from devtool_core.cli import main
        from devtool_core.cli.application import main as implementation
        from devtool_core.cli import main as after_import
        self.assertIs(main, after_import)
        self.assertTrue(callable(implementation))


if __name__ == "__main__":
    unittest.main()
