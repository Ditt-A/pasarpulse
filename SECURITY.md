# Security policy

## Reporting a vulnerability

Please report security issues privately to the repository owner instead of opening a public issue. Do not include live credentials, private infrastructure URLs, personal access tokens, API keys, or private datasets in an issue or pull request.

## Credential handling

PasarPulse reads runtime credentials only from environment variables or local credential files that are excluded by `.gitignore`. The repository intentionally contains only placeholder values in `.env.example`.

Before a public release, run:

```bash
python scripts/public_release_scan.py --history
```

The command fails on high-confidence provider tokens, private keys, literal secret assignments, private Jupyter infrastructure traces, and credential files accidentally tracked by Git.

If a real credential is ever committed, removing the file in a later commit is not enough. Revoke or rotate the credential first, rewrite the affected Git history, verify every reachable branch and tag, and require a clean history scan before publishing the repository.
