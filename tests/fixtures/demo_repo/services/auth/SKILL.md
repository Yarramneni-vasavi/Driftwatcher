# Auth skill

Sessions use a sliding expiry, see `session_expiry` in `services/auth/session.py`.

Run tests with `make test-auth`.

Use `create_session` from `services/auth/cli.py` to open a session.

The CLI in `services/auth/cli.py` supports `--dry-run`.

See `services/auth/missing.py` for the legacy helper.
