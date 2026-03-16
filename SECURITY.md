# Security Policy

## Supported Versions

`hx` is currently pre-1.0. Security fixes are made against the latest `main`
branch.

## Reporting

Report suspected vulnerabilities privately before public disclosure.

## Security Posture

- path sandbox allowlist and denylist are policy-driven
- commands are deny-by-default and prefix-allowlisted
- staged patch workflow blocks direct writes until obligations are satisfied
- audit logs capture tool use, decisions, touched files, and proof artifacts
- replay mode never replays model calls, only best-effort deterministic tool actions
