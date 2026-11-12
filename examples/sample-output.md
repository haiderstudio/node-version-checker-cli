== example project, Node 20: wanted >=20, matches ==
OK examples/package.json: found Node v20.17.0, wanted ">=20"
OK — 1 project(s) checked, Node satisfies every engines range.

== example project, Node 18: wanted >=20, does not match ==
FAIL examples/package.json: found Node v18.17.0, wanted ">=20"
Checked 1 project(s), 1 mismatch(es).

== old project, Node 18: wanted ^18.0.0, matches ==
OK examples/old-project/package.json: found Node v18.17.0, wanted "^18.0.0"
OK — 1 project(s) checked, Node satisfies every engines range.

== old project, Node 20: wanted ^18.0.0, does not match ==
FAIL examples/old-project/package.json: found Node v20.17.0, wanted "^18.0.0"
Checked 1 project(s), 1 mismatch(es).

== project with no engines.node: stops with exit 2 ==
