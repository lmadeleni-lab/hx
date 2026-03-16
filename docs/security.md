# Security

`hx` defaults to denial and asks workflows to earn broader access.

## Safe Defaults

- command prefix allowlist
- path sandbox allowlist and denylist
- timeout and output caps
- staged patch workflow instead of immediate writes
- audit trail for decisions and artifacts

## Threat Model

- accidental boundary-spanning edits
- arbitrary shell execution
- silent interface breakage
- untraceable agent actions

## Example Denials

- reading a file outside the active cell radius
- running a command whose prefix is not allowlisted
- committing a patch before proof obligations are satisfied
