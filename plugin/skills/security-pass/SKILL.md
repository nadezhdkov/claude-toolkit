---
name: security-pass
description: Review a change for security problems (injection, paths, auth, secrets, dependencies, CI) with evidence. Use before a PR that touches inputs, auth, shell or dependencies.
---

# Security pass

Review the **change**, not the whole codebase: `git diff <base>...` plus the
code it calls into. Report only what you can support with a concrete path
from input to impact; no generic advice.

## 1. Automated checks (when available)

- Secrets: `gitleaks git --staged --redact` or `gitleaks detect --redact`
  on the branch (the ctk `secrets` hook already scans each commit).
- Dependencies: if lockfiles changed, list added and upgraded packages
  (`git diff <base>... -- '*lock*' '*requirements*' go.sum Cargo.lock`).
  Run the ecosystem's audit (`npm audit`, `pip-audit`, `cargo audit`,
  `govulncheck`) only if it is installed; these contact the network, so
  ask first if the project has not used them before.
- GitHub Actions changes: `uvx zizmor --offline .github/workflows/`.

## 2. Manual review

For each changed entry point that receives outside data (HTTP handlers, CLI
arguments, files, environment, messages, webhooks, game network packets),
follow the data to where it is used and check:

- **Injection:** SQL built with string formatting; shell commands with
  `shell=True`, `exec`, backticks or string concatenation; template
  rendering of user input without escaping (XSS); regex built from input (ReDoS).
- **Paths:** user-controlled paths without normalisation and a root check
  (`..`, absolute paths, symlinks); archive extraction (zip slip).
- **AuthN/AuthZ:** new routes or actions without the same checks as their
  neighbours; IDs taken from the request without an ownership check (IDOR);
  admin-only behaviour reachable by other roles.
- **Deserialisation and parsing:** `pickle`, `yaml.load` without a safe
  loader, `eval`, XML with external entities, `ObjectInputStream`.
- **Network:** URLs from input fetched server-side (SSRF); TLS verification
  disabled; secrets in URLs or logs.
- **Secrets and data:** keys or tokens in code, configs, tests or fixtures;
  sensitive data in logs, errors or analytics.
- **Defaults:** debug mode, permissive CORS, wildcard permissions, world-writable
  files, new ports or services exposed.
- **Supply chain:** new dependencies (maintained? typosquatting? install
  scripts?), unpinned GitHub Actions, `pull_request_target` checking out PR code.

## 3. Report

One entry per real finding, most severe first:

```
[high|medium|low] <title>
Where: <file:line>
Path: <how outside input reaches it>
Impact: <what an attacker gets>
Fix: <the concrete change>
```

End with what was checked and found clean, and what could not be checked
(for example an audit tool that is not installed). If nothing was found, say
so in one line — do not pad the report.
