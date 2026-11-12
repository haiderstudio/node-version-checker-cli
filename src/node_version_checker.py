#!/usr/bin/env python3
"""Check the running Node version satisfies package.json (engines).

Run: python3 src/node_version_checker.py
     python3 src/node_version_checker.py examples/
     python3 src/node_version_checker.py --node-version 18.17.0 examples/

The problem is quiet: a project that needs Node 20 breaks in
confusing ways on Node 18, and the failure looks like a code
bug, not a version bug. This tool reads the version range from
the "engines" field of package.json, runs "node -v" to find
the Node version that is actually running, and says plainly
whether it satisfies the range — wanted ">=20", found
v18.17.0 — and exits 1 when it does not, so it can fail a CI
run. A matching version exits 0.

The range comes from "engines.node" in the nearest
package.json at or above the checked path, or from --package
to name one directly. --node-version checks a version number
directly instead of running node, and --node points at a
specific node binary, so a project can be checked against a
version that is not the one on PATH. With no "engines.node"
anywhere, the tool stops with exit 2 and says so plainly:
there is no version to check against, and guessing would
prove nothing.

It never installs or switches Node, and it never rewrites a
file. It is report-only and runs fully offline: it sends
nothing anywhere and needs no API key.

What it understands: the version ranges npm projects
actually write — ">=20", "^20.0.0", "~20.1.0", "20.x",
">=18 <21", "18 || 20", "18 - 20", and an exact version
such as "20.17.0". A leading "v" is allowed ("v20.17.0").
"*" or "latest" means any version passes. What it does NOT
do: it does not check npm, yarn, or pnpm versions, and it
does not read .nvmrc or .node-version files — only
"engines.node" in package.json.

Exit codes: 0 when the running Node satisfies the declared
range, 1 when it does not, 2 for a usage or input problem
(no package.json, no "engines.node", a range it cannot read,
no node found, a missing path, or a bad flag).

Python standard library only.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")
PART_RE = re.compile(r"^v?(\d+|x|X|\*)(?:\.(\d+|x|X|\*))?(?:\.(\d+|x|X|\*))?$")
HYPHEN_RE = re.compile(r"^(.+?)\s+-\s+(.+)$")


def display_path(path):
    """Return path as given, or relative to the working folder if absolute.

    The report must never print an absolute local path: a README
    quoting the output would carry one, and the same run on
    another machine would print a different one.
    """
    text = str(path)
    try:
        return str(Path(text).relative_to(Path.cwd()))
    except ValueError:
        return text


def parse_version(text):
    """Return a (major, minor, patch) tuple for "v20.17.0", or None.

    A leading "v" is allowed, missing parts default to 0, and a
    prerelease or build suffix ("-rc.1", "+build") is ignored.
    Anything else — "banana", "20.x", an empty string — gives
    None.
    """
    if text is None:
        return None
    match = VERSION_RE.match(text.strip())
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )


def format_version(version):
    """Return "20.17.0" for (20, 17, 0)."""
    return "%d.%d.%d" % version


def parse_partial(text):
    """Return (version, parts) for a partial version, or None.

    "20" gives ((20, 0, 0), 1); "20.1" gives ((20, 1, 0), 2);
    "20.1.2" gives ((20, 1, 2), 3). An "x" part counts as not
    given, so "20.x" is ((20, 0, 0), 1) and "20.1.x" is
    ((20, 1, 0), 2). A lone "x" is ((0, 0, 0), 0).
    """
    match = PART_RE.match(text.strip())
    if not match:
        return None
    parts = []
    given = 0
    for group in match.groups():
        if group is None or group in ("x", "X", "*"):
            parts.append(0)
        else:
            parts.append(int(group))
            given += 1
    return (tuple(parts), given)


def partial_upper(version, given):
    """Return the (op, version) upper bound for a partial version.

    A full version bounds exactly ("20.1.2" gives <= 20.1.2);
    a two-part version bounds the next minor ("20.1" gives
    < 20.2.0); a one-part version bounds the next major ("20"
    gives < 21.0.0).
    """
    if given >= 3:
        return ("<=", version)
    if given == 2:
        return ("<", (version[0], version[1] + 1, 0))
    return ("<", (version[0] + 1, 0, 0))


def parse_comparator(token):
    """Return a list of (op, version) comparators for one token, or None.

    "^20.0.0" gives >= 20.0.0 and < 21.0.0; "^0.1.2" gives
    >= 0.1.2 and < 0.2.0; "~20.1.0" gives >= 20.1.0 and
    < 20.2.0; ">=20" gives >= 20.0.0; "20" gives >= 20.0.0
    and < 21.0.0; "20.1.2" gives == 20.1.2; "x" gives no
    comparators at all, which matches everything.
    """
    token = token.strip()
    if not token:
        return None
    if token in ("*", "x", "X"):
        return []
    if token.startswith("^"):
        parsed = parse_partial(token[1:])
        if parsed is None:
            return None
        version, given = parsed
        # Caret pins the left-most non-zero part: ^20.0.0 allows
        # anything below 21, ^0.1.2 anything below 0.2, ^0.0.3
        # anything below 0.0.4.
        if version[0] > 0:
            upper = ("<", (version[0] + 1, 0, 0))
        elif version[1] > 0:
            upper = ("<", (0, version[1] + 1, 0))
        elif given >= 3:
            upper = ("<", (0, 0, version[2] + 1))
        elif given == 2:
            upper = ("<", (0, 1, 0))
        else:
            upper = ("<", (1, 0, 0))
        return [(">=", version), upper]
    if token.startswith("~"):
        parsed = parse_partial(token[1:])
        if parsed is None:
            return None
        version, given = parsed
        if given >= 2:
            upper = ("<", (version[0], version[1] + 1, 0))
        else:
            upper = ("<", (version[0] + 1, 0, 0))
        return [(">=", version), upper]
    for prefix, op in ((">=", ">="), ("<=", "<="), (">", ">"), ("<", "<")):
        if token.startswith(prefix):
            parsed = parse_partial(token[len(prefix):])
            if parsed is None:
                return None
            return [(op, parsed[0])]
    if token.startswith("=="):
        parsed = parse_partial(token[2:])
        if parsed is None:
            return None
        return [("==", parsed[0])]
    if token.startswith("="):
        parsed = parse_partial(token[1:])
        if parsed is None:
            return None
        return [("==", parsed[0])]
    parsed = parse_partial(token)
    if parsed is None:
        return None
    version, given = parsed
    if given >= 3:
        return [("==", version)]
    if given == 0:
        return []
    return [(">=", version), partial_upper(version, given)]


def parse_range(text):
    """Return OR-groups of comparators for a range string, or None.

    ">=20" gives one group; ">=18 <21" gives one group of two
    comparators (both must hold); "18 || 20" gives two groups
    (either may hold); "18 - 20" gives >= 18.0.0 and < 21.0.0.
    "*" and "latest" give one empty group, which matches any
    version. A string that cannot be read gives None.
    """
    if text is None:
        return None
    text = text.strip()
    if text in ("", "*", "latest"):
        return [[]]
    groups = []
    for part in text.split("||"):
        part = part.strip()
        if not part:
            return None
        hyphen = HYPHEN_RE.match(part)
        if hyphen:
            low = parse_partial(hyphen.group(1))
            high = parse_partial(hyphen.group(2))
            if low is None or high is None:
                return None
            groups.append(
                [(">=", low[0]), partial_upper(high[0], high[1])]
            )
            continue
        # A space between an operator and its version is allowed
        # (">= 20" means ">=20"), so glue them before splitting.
        part = re.sub(r"(>=|<=|>|<|=)\s+", r"\1", part)
        comparators = []
        for token in part.split():
            parsed = parse_comparator(token)
            if parsed is None:
                return None
            comparators.extend(parsed)
        groups.append(comparators)
    return groups


def compare(version, op, bound):
    """Return True when version stands in relation op to bound."""
    if op == ">=":
        return version >= bound
    if op == "<=":
        return version <= bound
    if op == ">":
        return version > bound
    if op == "<":
        return version < bound
    return version == bound


def satisfies(version, groups):
    """Return True when version satisfies any OR-group of comparators."""
    for group in groups:
        if all(compare(version, op, bound) for op, bound in group):
            return True
    return False


def read_engines(package_path):
    """Return (wanted, error) for the engines.node of a package.json.

    wanted is the declared range string, or None when the file
    has no "engines.node". error is a plain-language reason the
    file could not be read, or None when it was read fine.
    """
    try:
        text = package_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "cannot read %s (%s)" % (
            display_path(package_path),
            exc.strerror or exc,
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, "cannot read %s as JSON (%s)" % (
            display_path(package_path),
            exc.msg,
        )
    if not isinstance(data, dict):
        return None, "%s is not a JSON object" % display_path(package_path)
    engines = data.get("engines")
    if not isinstance(engines, dict):
        return None, None
    wanted = engines.get("node")
    if wanted is None:
        return None, None
    if not isinstance(wanted, str):
        return None, '"engines.node" in %s is not a string' % (
            display_path(package_path)
        )
    return wanted, None


def find_package_json(start):
    """Return the nearest package.json at or above start, or None.

    start may be a package.json file, a folder, or any file. The
    search walks up from the folder holding it, and stops at the
    filesystem root.
    """
    if start.is_file() and start.name == "package.json":
        return start
    folder = start if start.is_dir() else start.parent
    folder = folder.resolve()
    while True:
        candidate = folder / "package.json"
        if candidate.is_file():
            return candidate
        if folder.parent == folder:
            return None
        folder = folder.parent


def run_node(node_path):
    """Return (version, error) for running a node binary with -v.

    version is a (major, minor, patch) tuple, or None when the
    binary could not be run or its output could not be read.
    error is a plain-language reason, or None.
    """
    try:
        result = subprocess.run(
            [node_path, "-v"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return None, "node not found at %s" % node_path
    except OSError as exc:
        return None, "cannot run %s (%s)" % (
            node_path,
            exc.strerror or exc,
        )
    except subprocess.TimeoutExpired:
        return None, "%s took too long to answer -v" % node_path
    output = result.stdout.strip().splitlines()
    if result.returncode != 0 or not output:
        return None, "%s did not answer -v" % node_path
    version = parse_version(output[0].strip())
    if version is None:
        return None, "%s printed %r, which is not a version" % (
            node_path,
            output[0].strip(),
        )
    return version, None


def resolve_node_version(args):
    """Return (version, node_name, error) for the Node to check.

    --node-version wins: the version is taken as given, and no
    binary is run. Otherwise --node names a binary, and
    otherwise the node on PATH is used. node_name is what the
    report prints for where the version came from.
    """
    if args.node_version is not None:
        version = parse_version(args.node_version)
        if version is None:
            return None, None, (
                '--node-version must be a version like 20.17.0, '
                'got %r' % args.node_version
            )
        return version, "--node-version %s" % format_version(version), None
    node_path = args.node
    if node_path is None:
        node_path = shutil.which("node")
        if node_path is None:
            return None, None, (
                "node not found — install Node, or pass --node PATH "
                "to a node binary, or --node-version VERSION to "
                "check a version directly"
            )
    version, error = run_node(node_path)
    if error is not None:
        return None, None, error
    return version, node_path, None


def build_parser():
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="node_version_checker",
        description=(
            "Check the running Node version satisfies the version "
            "declared in package.json (engines)."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="project folders or package.json files to check "
        "(default: current folder)",
    )
    parser.add_argument(
        "--package",
        metavar="PATH",
        default=None,
        help="package.json to check (cannot be used with paths)",
    )
    parser.add_argument(
        "--node",
        metavar="PATH",
        default=None,
        help="node binary to check instead of the one on PATH",
    )
    parser.add_argument(
        "--node-version",
        metavar="VERSION",
        default=None,
        help="Node version to check, for example 18.17.0 "
        "(no node binary is run)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as machine-readable JSON",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s " + VERSION,
    )
    return parser


def main(argv=None):
    """Run the checker. Returns an exit code: 0 match, 1 mismatch, 2 usage."""
    parser = build_parser()
    args = parser.parse_args(argv)

    found, node_name, error = resolve_node_version(args)
    if error is not None:
        print("error: %s" % error, file=sys.stderr)
        return 2

    if args.package is not None:
        if args.paths:
            print(
                "error: --package cannot be used with paths — "
                "check one package.json at a time",
                file=sys.stderr,
            )
            return 2
        package_path = Path(args.package)
        if not package_path.is_file():
            print(
                "error: package.json not found: %s" % args.package,
                file=sys.stderr,
            )
            return 2
        package_paths = [package_path]
    else:
        paths = args.paths or ["."]
        for raw in paths:
            if not Path(raw).exists():
                print("error: path not found: %s" % raw, file=sys.stderr)
                return 2
        package_paths = []
        for raw in paths:
            found_package = find_package_json(Path(raw))
            if found_package is None:
                print(
                    "error: no package.json found at or above: %s" % raw,
                    file=sys.stderr,
                )
                return 2
            package_paths.append(found_package)

    results = []
    for package_path in package_paths:
        wanted, error = read_engines(package_path)
        if error is not None:
            print("error: %s" % error, file=sys.stderr)
            return 2
        if wanted is None:
            print(
                'error: no "engines.node" in %s — there is no '
                "version to check against. Add "
                '"engines": { "node": ">=20" } to package.json.'
                % display_path(package_path),
                file=sys.stderr,
            )
            return 2
        groups = parse_range(wanted)
        if groups is None:
            print(
                'error: "engines.node" in %s is not a version range '
                'I understand: %r' % (display_path(package_path), wanted),
                file=sys.stderr,
            )
            return 2
        results.append(
            {
                "package_json": display_path(package_path),
                "wanted": wanted,
                "found": format_version(found),
                "satisfied": satisfies(found, groups),
            }
        )

    mismatches = sum(1 for r in results if not r["satisfied"])
    checked = len(results)

    if args.json:
        payload = {
            "projects": [
                {
                    "package_json": r["package_json"],
                    "wanted": r["wanted"],
                    "found": r["found"],
                    "satisfied": r["satisfied"],
                }
                for r in results
            ],
            "summary": {
                "checked": checked,
                "matches": checked - mismatches,
                "mismatches": mismatches,
            },
        }
        print(json.dumps(payload, indent=2))
        if mismatches == 0:
            print(
                "OK — %d project(s) checked, Node satisfies every "
                "engines range." % checked,
                file=sys.stderr,
            )
        else:
            print(
                "Checked %d project(s), %d mismatch(es)."
                % (checked, mismatches),
                file=sys.stderr,
            )
    else:
        for result in results:
            if result["satisfied"]:
                print(
                    'OK %s: found Node v%s, wanted "%s"'
                    % (
                        result["package_json"],
                        result["found"],
                        result["wanted"],
                    )
                )
            else:
                print(
                    'FAIL %s: found Node v%s, wanted "%s"'
                    % (
                        result["package_json"],
                        result["found"],
                        result["wanted"],
                    )
                )
        if mismatches == 0:
            print(
                "OK — %d project(s) checked, Node satisfies every "
                "engines range." % checked
            )
        else:
            print(
                "Checked %d project(s), %d mismatch(es)."
                % (checked, mismatches)
            )

    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
