# Security Policy

This tool runs locally, collects no data, sends nothing anywhere, and needs no API key or secret. It only reads the `package.json` files you point it at and runs `node -v` (or the binary you name with `--node`), and it never rewrites a file, never installs anything, and never switches Node versions. It writes nothing except the report on standard output (and usage errors on standard error).

If you find a case where the tool changes a file, installs or switches Node, or reports a pass for a Node version outside the declared `engines.node` range, please open an issue describing the exact commands and input. Do not include any real secret in the report.
