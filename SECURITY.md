# Security Policy

## Supported versions

| Version        | Supported          |
| -------------- | ------------------ |
| `main` branch  | :white_check_mark: |
| Older releases | :x: (best effort)  |

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Email the maintainer at **vedantsawant2803@gmail.com** with:

- A description of the issue
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You can expect an acknowledgement within 7 days. Please allow reasonable time
for a fix before public disclosure.

## Scope notes specific to CareerOS

CareerOS is a local-first, citation-grounded assistant. Security-relevant
behaviors to keep in mind:

- **Secrets** live only in environment variables (`.env` is git-ignored).
  `.env.*.example` files must never contain real keys.
- **The Qdrant vector store** must not be exposed publicly without
  authentication — it contains the indexed profile corpus.
- **Personal contact information** (phone, personal email) is excluded from the
  public UI by default (`SHOW_CONTACT_INFORMATION=false`).
- **Prompt injection**: retrieved documents are treated as untrusted context.
  User input and document text are separated in prompts, and document content
  is never interpreted as instructions.
- **API authentication** (`API_KEY_ENABLED=true` + `X-API-Key`) should be
  enabled before any public deployment, with rate limiting at the reverse
  proxy.

See [docs/security.md](docs/security.md) for the full threat model and
configuration guidance.
