#!/usr/bin/env python3
"""Tests for node-version-checker-cli. Standard library unittest only.

Run from the repo root: python3 tests/test_node_version_checker.py
"""

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import node_version_checker as nvc  # noqa: E402

ALLOWED_STDLIB = {
    "argparse",
    "json",
    "os",
    "re",
    "shutil",
    "subprocess",
    "sys",
    "pathlib",
}


def run_cli(argv):
    """Run main() in-process and capture (exit code, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = nvc.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0
    return code, out.getvalue(), err.getvalue()


def write(path, text):
    """Write text to path, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_package(folder, engines_node=None, name="example-project"):
    """Write a package.json in folder, with engines.node if given."""
    if engines_node is None:
        data = {"name": name, "version": "1.0.0"}
    else:
        data = {
            "name": name,
            "version": "1.0.0",
            "engines": {"node": engines_node},
        }
    return write(folder / "package.json", json.dumps(data))


def write_fake_node(folder, version, name="node"):
    """Write an executable stand-in node script printing v<version>."""
    script = folder / name
    script.write_text("#!/bin/sh\necho v%s\n" % version, encoding="utf-8")
    script.chmod(0o755)
    return script


class TestParseVersion(unittest.TestCase):
    def test_plain_versions(self):
        self.assertEqual(nvc.parse_version("20.17.0"), (20, 17, 0))
        self.assertEqual(nvc.parse_version("v18.17.0"), (18, 17, 0))
        self.assertEqual(nvc.parse_version("20"), (20, 0, 0))
        self.assertEqual(nvc.parse_version("20.1"), (20, 1, 0))
        self.assertEqual(nvc.parse_version(" 20.17.0 "), (20, 17, 0))

    def test_prerelease_and_build_suffixes_ignored(self):
        self.assertEqual(nvc.parse_version("20.0.0-rc.1"), (20, 0, 0))
        self.assertEqual(nvc.parse_version("20.17.0+build"), (20, 17, 0))

    def test_bad_versions(self):
        for bad in ("banana", "20.x", "v", "", "20.17.0.1", "20..1"):
            self.assertIsNone(nvc.parse_version(bad), bad)

    def test_format_version(self):
        self.assertEqual(nvc.format_version((20, 17, 0)), "20.17.0")
        self.assertEqual(nvc.format_version((18, 0, 0)), "18.0.0")


class TestParseRange(unittest.TestCase):
    def test_simple_ranges(self):
        self.assertEqual(
            nvc.parse_range(">=20"), [[(">=", (20, 0, 0))]]
        )
        self.assertEqual(
            nvc.parse_range("20.17.0"), [[("==", (20, 17, 0))]]
        )
        self.assertEqual(nvc.parse_range("*"), [[]])
        self.assertEqual(nvc.parse_range("latest"), [[]])

    def test_caret_ranges(self):
        self.assertEqual(
            nvc.parse_range("^20.0.0"),
            [[(">=", (20, 0, 0)), ("<", (21, 0, 0))]],
        )
        self.assertEqual(
            nvc.parse_range("^0.1.2"),
            [[(">=", (0, 1, 2)), ("<", (0, 2, 0))]],
        )
        self.assertEqual(
            nvc.parse_range("^0.0.3"),
            [[(">=", (0, 0, 3)), ("<", (0, 0, 4))]],
        )

    def test_tilde_ranges(self):
        self.assertEqual(
            nvc.parse_range("~20.1.0"),
            [[(">=", (20, 1, 0)), ("<", (20, 2, 0))]],
        )
        self.assertEqual(
            nvc.parse_range("~20"),
            [[(">=", (20, 0, 0)), ("<", (21, 0, 0))]],
        )

    def test_x_ranges(self):
        self.assertEqual(
            nvc.parse_range("20.x"),
            [[(">=", (20, 0, 0)), ("<", (21, 0, 0))]],
        )
        self.assertEqual(
            nvc.parse_range("20.1.x"),
            [[(">=", (20, 1, 0)), ("<", (20, 2, 0))]],
        )
        self.assertEqual(
            nvc.parse_range("20"),
            [[(">=", (20, 0, 0)), ("<", (21, 0, 0))]],
        )

    def test_and_or_and_hyphen(self):
        self.assertEqual(
            nvc.parse_range(">=18 <21"),
            [[(">=", (18, 0, 0)), ("<", (21, 0, 0))]],
        )
        self.assertEqual(
            nvc.parse_range("18 || 20"),
            [
                [(">=", (18, 0, 0)), ("<", (19, 0, 0))],
                [(">=", (20, 0, 0)), ("<", (21, 0, 0))],
            ],
        )
        self.assertEqual(
            nvc.parse_range("18 - 20"),
            [[(">=", (18, 0, 0)), ("<", (21, 0, 0))]],
        )
        self.assertEqual(
            nvc.parse_range(">= 20"),
            [[(">=", (20, 0, 0))]],
        )

    def test_bad_ranges(self):
        for bad in ("banana", ">=banana", "||", ">=20 ||", "^banana", "~"):
            self.assertIsNone(nvc.parse_range(bad), bad)


SATISFIES_CASES = [
    ((20, 17, 0), ">=20", True),
    ((18, 17, 0), ">=20", False),
    ((20, 17, 0), "^20.0.0", True),
    ((21, 0, 0), "^20.0.0", False),
    ((20, 0, 0), "^20.0.0", True),
    ((0, 1, 5), "^0.1.2", True),
    ((0, 2, 0), "^0.1.2", False),
    ((0, 0, 3), "^0.0.3", True),
    ((0, 0, 4), "^0.0.3", False),
    ((20, 1, 5), "~20.1.0", True),
    ((20, 2, 0), "~20.1.0", False),
    ((20, 0, 0), "20.x", True),
    ((21, 0, 0), "20.x", False),
    ((20, 1, 5), "20.1.x", True),
    ((20, 2, 0), "20.1.x", False),
    ((18, 17, 0), "18 || 20", True),
    ((20, 17, 0), "18 || 20", True),
    ((19, 0, 0), "18 || 20", False),
    ((20, 5, 0), "18 - 20", True),
    ((21, 0, 0), "18 - 20", False),
    ((18, 0, 0), "18 - 20", True),
    ((20, 17, 0), "20.17.0", True),
    ((20, 17, 1), "20.17.0", False),
    ((24, 22, 1), "*", True),
    ((24, 22, 1), "latest", True),
    ((18, 17, 0), ">=18 <21", True),
    ((21, 0, 0), ">=18 <21", False),
    ((20, 0, 0), "v20", True),
    ((21, 0, 0), "v20", False),
    ((20, 17, 0), "=20.17.0", True),
    ((20, 17, 0), ">20", True),
    ((20, 0, 0), ">20", False),
    ((21, 0, 0), ">20", True),
    ((20, 0, 0), "<=20", True),
    ((20, 0, 1), "<=20", False),
]


class TestSatisfies(unittest.TestCase):
    def test_table(self):
        for version, range_text, expected in SATISFIES_CASES:
            groups = nvc.parse_range(range_text)
            self.assertIsNotNone(groups, range_text)
            self.assertEqual(
                nvc.satisfies(version, groups),
                expected,
                "%s against %r" % (version, range_text),
            )


class TestReadEngines(unittest.TestCase):
    def test_engines_node_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            wanted, error = nvc.read_engines(package)
            self.assertEqual(wanted, ">=20")
            self.assertIsNone(error)

    def test_no_engines_and_no_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plain = write_package(folder)
            wanted, error = nvc.read_engines(plain)
            self.assertIsNone(wanted)
            self.assertIsNone(error)
            other = write(
                folder / "other.json",
                '{"name": "x", "engines": {"npm": ">=9"}}',
            )
            wanted, error = nvc.read_engines(other)
            self.assertIsNone(wanted)
            self.assertIsNone(error)

    def test_bad_json_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            bad = write(folder / "bad.json", "{not json")
            wanted, error = nvc.read_engines(bad)
            self.assertIsNone(wanted)
            self.assertIn("JSON", error)
            wanted, error = nvc.read_engines(folder / "gone.json")
            self.assertIsNone(wanted)
            self.assertIn("cannot read", error)

    def test_non_string_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write(
                folder / "package.json",
                '{"engines": {"node": 20}}',
            )
            wanted, error = nvc.read_engines(package)
            self.assertIsNone(wanted)
            self.assertIn("not a string", error)

    def test_find_package_json_walks_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_package(root, ">=20")
            deep = root / "a" / "b"
            deep.mkdir(parents=True)
            found = nvc.find_package_json(deep / "code.js")
            self.assertEqual(found, (root / "package.json").resolve())

    def test_find_package_json_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                nvc.find_package_json(Path(tmp) / "code.js")
            )

    def test_find_package_json_direct_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            self.assertEqual(nvc.find_package_json(package), package)


class TestRunNode(unittest.TestCase):
    def test_fake_node_on_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_fake_node(folder, "18.17.0")
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(folder) + os.pathsep + old_path
            try:
                found = shutil.which("node")
                self.assertEqual(found, str(folder / "node"))
                version, error = nvc.run_node(found)
                self.assertEqual(version, (18, 17, 0))
                self.assertIsNone(error)
            finally:
                os.environ["PATH"] = old_path

    def test_missing_node_binary(self):
        version, error = nvc.run_node("/no-such-dir/node")
        self.assertIsNone(version)
        self.assertIn("not found", error)

    def test_garbage_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            script = folder / "node"
            script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            script.chmod(0o755)
            version, error = nvc.run_node(str(script))
            self.assertIsNone(version)
            self.assertIn("not a version", error)

    @unittest.skipUnless(
        shutil.which("node"), "no real node on PATH"
    )
    def test_real_node_answers(self):
        version, error = nvc.run_node(shutil.which("node"))
        self.assertIsNone(error)
        self.assertEqual(len(version), 3)
        self.assertGreaterEqual(version[0], 10)


class TestCli(unittest.TestCase):
    def test_match_with_fake_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            fake = write_fake_node(folder, "20.17.0", "fake-node")
            code, out, _ = run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(code, 0)
            self.assertIn(folder.name + "/package.json", out)
            self.assertIn(
                'OK', out,
            )
            self.assertIn('found Node v20.17.0, wanted ">=20"', out)
            self.assertIn("satisfies every engines range", out)

    def test_mismatch_names_wanted_and_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            fake = write_fake_node(folder, "18.17.0", "fake-node")
            code, out, _ = run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(code, 1)
            self.assertIn(folder.name + "/package.json", out)
            self.assertIn('FAIL', out)
            self.assertIn('found Node v18.17.0, wanted ">=20"', out)
            self.assertIn("1 mismatch(es)", out)

    def test_node_on_path_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder, ">=20")
            write_fake_node(folder, "20.17.0")
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(folder) + os.pathsep + old_path
            try:
                code, out, _ = run_cli([str(folder)])
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(code, 0)
            self.assertIn("found Node v20.17.0", out)

    def test_no_node_anywhere_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder, ">=20")
            bin_dir = folder / "empty-bin"
            bin_dir.mkdir()
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(bin_dir)
            try:
                code, _, err = run_cli([str(folder)])
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(code, 2)
            self.assertIn("node not found", err)

    def test_no_engines_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder)
            fake = write_fake_node(folder, "20.17.0", "fake-node")
            code, _, err = run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(code, 2)
            self.assertIn('no "engines.node"', err)
            self.assertIn('">=20"', err)

    def test_no_package_json_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fake = write_fake_node(folder, "20.17.0", "fake-node")
            code, _, err = run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(code, 2)
            self.assertIn("no package.json", err)

    def test_bad_range_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder, "banana")
            fake = write_fake_node(folder, "20.17.0", "fake-node")
            code, _, err = run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(code, 2)
            self.assertIn("not a version range", err)
            self.assertIn("banana", err)

    def test_bad_json_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder / "package.json", "{not json")
            fake = write_fake_node(folder, "20.17.0", "fake-node")
            code, _, err = run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(code, 2)
            self.assertIn("JSON", err)

    def test_missing_path_is_exit_2(self):
        code, _, err = run_cli(
            ["--node-version", "20.17.0", "no-such-folder"]
        )
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_node_version_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder, "^18.0.0")
            code, out, _ = run_cli(
                ["--node-version", "18.17.0", str(folder)]
            )
            self.assertEqual(code, 0)
            self.assertIn("found Node v18.17.0", out)
            code, _, _ = run_cli(
                ["--node-version", "20.17.0", str(folder)]
            )
            self.assertEqual(code, 1)

    def test_bad_node_version_is_exit_2(self):
        code, _, err = run_cli(["--node-version", "banana", "."])
        self.assertEqual(code, 2)
        self.assertIn("--node-version must be", err)

    def test_package_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            fake = write_fake_node(folder, "18.17.0", "fake-node")
            code, out, _ = run_cli(
                ["--node", str(fake), "--package", str(package)]
            )
            self.assertEqual(code, 1)
            self.assertIn('wanted ">=20"', out)

    def test_package_flag_with_paths_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            code, _, err = run_cli(
                ["--package", str(package), str(folder)]
            )
            self.assertEqual(code, 2)
            self.assertIn("--package cannot be used with paths", err)

    def test_package_flag_missing_file_is_exit_2(self):
        code, _, err = run_cli(
            ["--package", "no-such-package.json", "--node-version", "20.0.0"]
        )
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_two_projects_in_one_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder / "a", ">=20")
            write_package(folder / "b", "^18.0.0")
            fake = write_fake_node(folder, "18.17.0", "fake-node")
            code, out, _ = run_cli(
                ["--node", str(fake), str(folder / "a"), str(folder / "b")]
            )
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 project(s), 1 mismatch(es).", out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_package(folder, ">=20")
            fake = write_fake_node(folder, "18.17.0", "fake-node")
            code, out, err = run_cli(
                ["--node", str(fake), "--json", str(folder)]
            )
            self.assertEqual(code, 1)
            payload = json.loads(out)
            self.assertEqual(payload["summary"]["checked"], 1)
            self.assertEqual(payload["summary"]["mismatches"], 1)
            self.assertEqual(payload["projects"][0]["wanted"], ">=20")
            self.assertEqual(payload["projects"][0]["found"], "18.17.0")
            self.assertFalse(payload["projects"][0]["satisfied"])
            self.assertIn("Checked 1 project(s)", err)

    def test_version_flag(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("1.0.0", out)

    def test_bad_flag_is_exit_2(self):
        code, _, _ = run_cli(["--nope"])
        self.assertEqual(code, 2)

    def test_input_files_are_not_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            package = write_package(folder, ">=20")
            before = package.read_text(encoding="utf-8")
            fake = write_fake_node(folder, "18.17.0", "fake-node")
            run_cli(["--node", str(fake), str(folder)])
            self.assertEqual(package.read_text(encoding="utf-8"), before)

    @unittest.skipUnless(
        shutil.which("node"), "no real node on PATH"
    )
    def test_real_node_runs(self):
        code, out, _ = run_cli([str(REPO_ROOT / "examples")])
        self.assertIn(code, (0, 1))
        self.assertIn("found Node v", out)
        self.assertIn('wanted ">=20"', out)


class TestBundledExamples(unittest.TestCase):
    def test_example_project_matches_node_20(self):
        fake = REPO_ROOT / "examples" / "fake-node-20.sh"
        previous = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            code, out, _ = run_cli(["--node", str(fake), "examples"])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 0)
        self.assertIn(
            'OK examples/package.json: found Node v20.17.0, '
            'wanted ">=20"',
            out,
        )

    def test_example_project_fails_node_18(self):
        fake = REPO_ROOT / "examples" / "fake-node-18.sh"
        previous = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            code, out, _ = run_cli(["--node", str(fake), "examples"])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 1)
        self.assertIn(
            'FAIL examples/package.json: found Node v18.17.0, '
            'wanted ">=20"',
            out,
        )

    def test_old_project_matches_node_18_not_20(self):
        old = REPO_ROOT / "examples" / "old-project"
        fake18 = REPO_ROOT / "examples" / "fake-node-18.sh"
        fake20 = REPO_ROOT / "examples" / "fake-node-20.sh"
        previous = os.getcwd()
        os.chdir(REPO_ROOT)
        try:
            code, out, _ = run_cli(["--node", str(fake18), "examples/old-project"])
            self.assertEqual(code, 0)
            self.assertIn('wanted "^18.0.0"', out)
            code, out, _ = run_cli(["--node", str(fake20), "examples/old-project"])
        finally:
            os.chdir(previous)
        self.assertEqual(code, 1)
        self.assertIn(
            'FAIL examples/old-project/package.json: found Node '
            'v20.17.0, wanted "^18.0.0"',
            out,
        )

    def test_no_engines_example_needs_engines(self):
        fake = REPO_ROOT / "examples" / "fake-node-20.sh"
        code, _, err = run_cli(
            ["--node", str(fake), str(REPO_ROOT / "examples" / "no-engines")]
        )
        self.assertEqual(code, 2)
        self.assertIn('no "engines.node"', err)

    def test_run_example_script_matches_sample_output(self):
        script = REPO_ROOT / "examples" / "run-example.sh"
        result = subprocess.run(
            ["sh", str(script)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0)
        sample = (REPO_ROOT / "examples" / "sample-output.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(result.stdout, sample)

    def test_readme_quotes_real_output(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for line in (
            'OK examples/package.json: found Node v20.17.0, wanted ">=20"',
            'FAIL examples/package.json: found Node v18.17.0, wanted ">=20"',
            'OK examples/old-project/package.json: found Node v18.17.0, wanted "^18.0.0"',
            'FAIL examples/old-project/package.json: found Node v20.17.0, wanted "^18.0.0"',
            "Checked 1 project(s), 1 mismatch(es).",
            "OK — 1 project(s) checked, Node satisfies every engines range.",
            'error: no "engines.node" in examples/no-engines/package.json',
        ):
            self.assertIn(line, readme, line)


class TestHygiene(unittest.TestCase):
    def test_no_placeholder_text(self):
        banned = ("TODO", "coming soon", "lorem")
        hits = []
        for path in REPO_ROOT.rglob("*"):
            if (
                ".git" in path.parts
                or "__pycache__" in path.parts
                or "tests" in path.parts
            ):
                continue
            if path.is_file() and path.suffix in (
                ".py",
                ".md",
                ".json",
                ".yml",
                ".sh",
            ):
                text = path.read_text(encoding="utf-8", errors="replace")
                for word in banned:
                    if word in text:
                        hits.append("%s: %s" % (path, word))
        self.assertEqual(hits, [])

    def test_no_absolute_local_paths(self):
        hits = []
        for path in REPO_ROOT.rglob("*"):
            if (
                ".git" in path.parts
                or "__pycache__" in path.parts
                or "tests" in path.parts
            ):
                continue
            if path.is_file() and path.suffix in (
                ".py",
                ".md",
                ".json",
                ".yml",
                ".sh",
            ):
                text = path.read_text(encoding="utf-8", errors="replace")
                if "/home/" in text or "/Users/" in text or "C:\\" in text:
                    hits.append(str(path))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        source = (REPO_ROOT / "src" / "node_version_checker.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        extra = imports - ALLOWED_STDLIB
        self.assertEqual(extra, set())

    def test_env_first_in_gitignore(self):
        lines = (REPO_ROOT / ".gitignore").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_the_test_file(self):
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tests/test_node_version_checker.py", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("checkout", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_no_secrets(self):
        for path in REPO_ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.is_file() and path.name == ".env":
                self.fail(".env file must not ship: %s" % path)


if __name__ == "__main__":
    unittest.main()
