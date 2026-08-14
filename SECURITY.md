# Security Policy

## Supported Versions

Security fixes are applied to the latest release and the default branch.

## Reporting a Vulnerability

Use GitHub's private vulnerability reporting for `MAnasLatif/CTO`. Do not open a
public issue for an unpatched vulnerability or include credentials, tokens, or
private production data in any report.

Include the affected file or workflow, reproduction conditions, impact, and any
suggested mitigation. You should receive an acknowledgement within seven days.

## Third-Party Specialists

The public repository does not vendor specialist payloads. Report a vulnerability
in an upstream specialist to its owner. Also report it here when the CTO wrapper,
selection logic, synchronization process, or documented integration materially
increases the impact.

Synchronization downloads files but does not execute third-party scripts. Treat
locally synchronized content as untrusted until reviewed.