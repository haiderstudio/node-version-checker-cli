# node-version-checker-cli

Check the running Node version satisfies package.json (engines), fail CI on a mismatch.

[![CI](https://github.com/haiderstudio/node-version-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/node-version-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`node_version_checker` reads the Node version your project
asks for from `package.json` (`engines.node`) and checks the
Node version that is actually running against it:

- A project that needs Node 20 breaks in confusing ways on
  Node 18, and the failure looks like a code bug, not a
  version bug. This tool catches that before it costs an
  hour: it runs `node -v`, compares the result with the
  range in `engines.node`, reports the mismatch with the
  version wanted and the version found, and exits 1 when
  they do not match — so it can fail a CI run. A matching
  version exits 0.
- The wanted version comes from `engines.node` in the
  nearest `package.json` at or above the checked path.
  `--package PATH` names a `package.json` directly, and
  several project folders can be checked in one run.
- `--node PATH` checks a specific node binary instead of
  the one on PATH, and `--node-version VERSION` checks a
  version number directly without running node at all — so
  a project can be checked against a version that is not
  installed on the machine running the check.
- **With no `engines.node` and no `--node-version`, the
  tool stops with exit 2 and says so plainly.** There is
  no version to check against, and guessing would prove
  nothing. Add `"engines": { "node": ">=20" }` to
  `package.json`.
- It understands the version ranges npm projects actually
  write: `>=20`, `^20.0.0`, `~20.1.0`, `20.x`, `>=18 <21`,
  `18 || 20`, `18 - 20`, and an exact version such as
  `20.17.0`. A leading `v` is allowed (`v20.17.0`). `*` or
  `latest` means any version passes.
- `--json` prints the result as machine-readable JSON (the
  summary goes to standard error, so standard output stays
  clean JSON).
- It is report-only and runs fully offline: it never
  installs or switches Node, never edits a file, sends
  nothing anywhere, and needs no API key. Python standard
  library only — the check is one `node -v` call plus a
  range comparison.

## What it does NOT do

- It does not install or switch Node versions. It checks
  the version that is running; getting the right version
  installed is your job (nvm, Volta, or your package
  manager).
- It does not check npm, yarn, or pnpm versions — only
  Node. Those tools have their own version numbers, and a
  matching Node does not mean a matching npm.
- It does not read `.nvmrc` or `.node-version` files —
  only `engines.node` in `package.json`.
- It does not fix, rewrite, or convert any file. A version
  mismatch is reported; changing the range or the Node
  version is your job.

## Who it is for

Anyone shipping a Node project to more than one machine: a
developer whose laptop runs Node 24 while the server runs
Node 18, a team adding a CI step that fails the build when
someone runs the wrong Node, or a new contributor who
wants a one-line answer to "am I on the right Node for
this project?" instead of an hour of strange errors. A
version slip is invisible in the code itself — this catches
it before it goes live.

## How this differs from similar tools

The exact name `node-version-checker-cli` matches 0
repositories on GitHub (checked Nov 9, 2026), and the
wider field `node version checker` matches 59 — mostly
noise about other things' versions. Two tools do the exact
job, and both were re-checked on Nov 11, 2026:

- gobold/node-version-checker, 6 stars — the exact job
  ("checking if the current node version matches what is
  provided in the `engines` section"), but unmaintained:
  created in 2015, and its own issue #7 ("nvc should exit
  with 1 and not 0 if failure", opened Dec 15, 2017) was
  never fixed, so it cannot gate CI.
- parshap/check-node-version, 77 stars — a real npm
  package that checks node, npm, npx, yarn, and pnpm
  against given ranges or `package.json` engines, and it
  does exit with an error code. It is a five-tool checker
  you install with npm; this tool is one job only (Node),
  Python standard-library only, with nothing to install —
  it runs in any CI image that has Python, even one without
  npm.

This tool does that one job: a tested Python CLI that reads
`engines.node`, runs `node -v`, and exits 1 for CI — no
install beyond Python, no website, no network.

## Install

Python standard library only — no packages to download. You need
Python 3.8 or newer, and Node on PATH (or pass `--node` /
`--node-version`). Clone the repo and run it in place:

```
git clone https://github.com/haiderstudio/node-version-checker-cli.git
cd node-version-checker-cli
python3 src/node_version_checker.py examples/
```

```
OK examples/package.json: found Node v24.22.1, wanted ">=20"
OK — 1 project(s) checked, Node satisfies every engines range.
```

(The version shown is the one on this machine — yours will
differ. The examples below use the stand-in node scripts in
`examples/` so their output is the same everywhere.)

## Usage

Check a project folder — the wanted version comes from
`engines.node` in the nearest `package.json` (here
`>=20`):

```
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/
```

```
OK examples/package.json: found Node v20.17.0, wanted ">=20"
OK — 1 project(s) checked, Node satisfies every engines range.
```

The same project against Node 18 — a mismatch, exit 1:

```
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/
```

```
FAIL examples/package.json: found Node v18.17.0, wanted ">=20"
Checked 1 project(s), 1 mismatch(es).
```

Check a project that pins Node 18 (`^18.0.0`) — Node 18
passes, Node 20 does not:

```
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/old-project
```

```
OK examples/old-project/package.json: found Node v18.17.0, wanted "^18.0.0"
OK — 1 project(s) checked, Node satisfies every engines range.
```

```
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/old-project
```

```
FAIL examples/old-project/package.json: found Node v20.17.0, wanted "^18.0.0"
Checked 1 project(s), 1 mismatch(es).
```

Check a version number directly, without running node:

```
python3 src/node_version_checker.py --node-version 18.17.0 examples/old-project
```

```
OK examples/old-project/package.json: found Node v18.17.0, wanted "^18.0.0"
OK — 1 project(s) checked, Node satisfies every engines range.
```

Check two projects in one run:

```
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/ examples/old-project
```

```
FAIL examples/package.json: found Node v18.17.0, wanted ">=20"
OK examples/old-project/package.json: found Node v18.17.0, wanted "^18.0.0"
Checked 2 project(s), 1 mismatch(es).
```

A project with no `engines.node` stops with exit 2, and
says what to do:

```
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/no-engines
```

```
error: no "engines.node" in examples/no-engines/package.json — there is no version to check against. Add "engines": { "node": ">=20" } to package.json.
```

Machine-readable output with `--json` (the summary goes to
standard error, so standard output stays clean JSON):

```
python3 src/node_version_checker.py --json --node examples/fake-node-18.sh examples/
```

```
{
  "projects": [
    {
      "package_json": "examples/package.json",
      "wanted": ">=20",
      "found": "18.17.0",
      "satisfied": false
    }
  ],
  "summary": {
    "checked": 1,
    "matches": 0,
    "mismatches": 1
  }
}
```

Exit codes: 0 when the running Node satisfies the declared
range, 1 when it does not, 2 for a usage problem (no
`package.json`, no `engines.node`, a range it cannot read,
no node found, a missing path, or a bad flag).

## Examples

### 1. A project that wants Node 20, checked against Node 20 and Node 18

`examples/package.json` declares `"engines": { "node":
">=20" }`. Node 20.17.0 passes; Node 18.17.0 fails with
the wanted and found versions side by side:

```
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/
```

```
OK examples/package.json: found Node v20.17.0, wanted ">=20"
OK — 1 project(s) checked, Node satisfies every engines range.
```

```
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/
```

```
FAIL examples/package.json: found Node v18.17.0, wanted ">=20"
Checked 1 project(s), 1 mismatch(es).
```

### 2. A project pinned to Node 18, checked against both versions

`examples/old-project/package.json` declares `"engines":
{ "node": "^18.0.0" }` — a caret range, so Node 18 passes
and Node 20 fails:

```
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/old-project
```

```
OK examples/old-project/package.json: found Node v18.17.0, wanted "^18.0.0"
OK — 1 project(s) checked, Node satisfies every engines range.
```

```
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/old-project
```

```
FAIL examples/old-project/package.json: found Node v20.17.0, wanted "^18.0.0"
Checked 1 project(s), 1 mismatch(es).
```

### 3. The bundled examples, all at once

```
sh examples/run-example.sh
```

The script checks the example project against Node 20
(pass) and Node 18 (fail, on purpose), then the old
project against Node 18 (pass) and Node 20 (fail, on
purpose), then a project with no `engines.node` (stops
with exit 2, on purpose). Its full output is in
`examples/sample-output.md`, ending with the no-engines
error on standard error. The failing runs exit 1, which
is the expected result — the script ends with exit 0 so
it can be run as a demo.

## How it is tested

Tests, standard library `unittest` only, no packages to install:

```
python3 tests/test_node_version_checker.py
```

The tests cover: version parsing (`v20.17.0`, partial
versions, prerelease suffixes, bad values rejected),
range parsing (`>=20`, `^20.0.0` including the `^0.x`
rules, `~20.1.0`, `20.x`, `>=18 <21`, `18 || 20`,
`18 - 20`, exact versions, `*`, bad ranges rejected),
the comparison itself (a table of versions against
ranges, pass and fail both ways), reading `engines.node`
(a missing `engines` field, `engines` without `node`, bad
JSON, a non-string value), finding the nearest
`package.json` by walking up, running node (a stand-in
`node` script on PATH, `--node` pointing at a binary, a
missing node, garbage output from `node -v`), the CLI
(exit 0/1/2, a mismatch naming the wanted and found
versions, no `engines.node` stopping with exit 2, a bad
range, a missing path, `--package`, `--node-version`,
`--json` output, `--version`, bad flags, two projects in
one run, input files left unchanged), the bundled
examples (sample output compared byte-for-byte against a
fresh run, and the README-quoted outputs checked against
it), and hygiene checks (no placeholder text, no absolute
paths, stdlib imports only, `.env` first in `.gitignore`,
CI file runs the test file).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea of
checking the running Node version against `package.json`
engines is not new — the similar tools named above
(gobold/node-version-checker and parshap/check-node-version)
do the same job — but every line of code here is original,
and the tool builds on nothing but Python's standard library.
