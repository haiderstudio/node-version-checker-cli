#!/bin/sh
# Check the bundled examples. The failing runs exit 1 on purpose,
# so each one ends with "|| true"; the script itself ends with
# exit 0 so it can be run as a demo. Run from the repo root:
# sh examples/run-example.sh
# The examples use the stand-in node scripts in this folder
# (fake-node-18.sh, fake-node-20.sh) so the output is the same
# on every machine — the tool runs them exactly as it would
# run a real node binary.
cd "$(dirname "$0")/.."
echo "== example project, Node 20: wanted >=20, matches =="
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/ || true
echo
echo "== example project, Node 18: wanted >=20, does not match =="
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/ || true
echo
echo "== old project, Node 18: wanted ^18.0.0, matches =="
python3 src/node_version_checker.py --node examples/fake-node-18.sh examples/old-project || true
echo
echo "== old project, Node 20: wanted ^18.0.0, does not match =="
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/old-project || true
echo
echo "== project with no engines.node: stops with exit 2 =="
python3 src/node_version_checker.py --node examples/fake-node-20.sh examples/no-engines || true
