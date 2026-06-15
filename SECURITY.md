# Security Policy

SourceScout is a local routing and diagnostics tool. It is designed to be read-only by default.

## Security boundaries

SourceScout must not automatically:

- read browser cookies
- print secret values
- dump environment variables
- write credentials
- post to social platforms
- buy API credits
- install global packages
- mutate Hermes routing or config

High-risk channels must be marked `approval_required` in machine-readable output.

## Reporting a vulnerability

Open a GitHub issue if the report does not contain secrets.

If the report includes a real secret, private credential, account token, or exploit against a live system, do **not** paste it into a public issue. Contact the maintainer privately and include:

- affected version or commit
- exact command run
- what value leaked or what action occurred
- expected safe behavior
- actual behavior

## Maintainer checklist before release

```bash
python3 -m py_compile source_scout/*.py
python3 -m pytest -q
python3 -m source_scout doctor --format json
python3 -m source_scout routes --format json
```

Also run a real secret scanner or your platform's protected-secret checks before publishing. The expected result is no real secret values in tracked files or git history. Mentions of credential names or policy text are acceptable when they do not expose values.
