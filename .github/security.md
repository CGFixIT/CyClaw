# Security Policy for PsyClaw

## Supported Versions


| State               | Supported          |
| ------------------- | ------------------ |
| Latest (`main`)     | :white_check_mark: |
| Any prior commit    | :x:                |

> **Recommendation:** Always pull the latest version from `main` before running in production environments.

---

## Scope

This tool parses and summarizes Veeam Health Check HTML/JSON reports. Security considerations relevant to this project include:

- **Path traversal / arbitrary file read** — malicious input file paths passed to the script
- **Unsafe deserialization** — processing of crafted/malformed Veeam report files
- **Credential exposure** — accidental logging or surfacing of sensitive data present in Veeam reports (e.g., repository names, job credentials, server hostnames)
- **Dependency vulnerabilities** — issues in packages listed in `requirements.txt`
- **Code injection** — any vector allowing execution of unintended code via report content

Out of scope: vulnerabilities in Veeam Backup & Replication itself, or issues requiring physical/administrative access to the host running this script.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues privately via one of the following:

- **Email:** [security@cgfixit.com](mailto:contact@cgfixit.com)
- **Web:** [https://cgfixit.com](https://cgfixit.com) (use the contact form and mark subject as `[SECURITY]`)

### What to Include

To help triage effectively, please provide:

1. A clear description of the vulnerability and its potential impact
2. Steps to reproduce (include a sanitized/minimal sample report file if applicable)
3. The environment details (OS, Python version, relevant dependencies from `requirements.txt`)
4. Any suggested remediation, if you have one

### Response Timeline

| Milestone                        | Target Timeframe     |
| -------------------------------- | -------------------- |
| Acknowledgment of report         | Within **48 hours**  |
| Initial triage / severity rating | Within **5 days**    |
| Fix or mitigation published      | Within **14 days**   |
| Public disclosure (if warranted) | After fix is live    |

These are best-effort targets for a solo-maintained open-source project. Complex issues may take longer; you will be kept informed.

### Outcome

- **Accepted vulnerabilities** will receive a fix on `main` and a note in the commit message referencing the report (reporter credited by name/handle if desired).
- **Declined reports** will receive a clear explanation of why the finding is out of scope or not actionable.

---

## Dependency Security

Dependencies are tracked in [`requirements.txt`](./requirements.txt). It is recommended to:

```bash
pip install --upgrade -r requirements.txt
pip-audit -r requirements.txt   # requires pip-audit
```

Report any known CVEs in listed packages using the process above.

---

## Disclosure Policy

This project follows **responsible disclosure**. Public details of a confirmed vulnerability will not be released until a fix is available or a reasonable remediation window (14 days) has passed without resolution, whichever comes first.
