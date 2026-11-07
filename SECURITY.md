# Security

Report suspected vulnerabilities privately, with GitHub's
[Report a vulnerability](https://github.com/row-and-reason/rowlab/security/advisories/new) or by
email to **support@rowandreason.com**. Include the version or commit, steps to reproduce and the
impact. Don't open a public issue for an undisclosed vulnerability, and don't include real
credentials or other people's data.

rowlab is pre-1.0: fixes go into the main branch and the next release; older versions get none.

## Deployment boundaries

- **Local mode has no sign-in.** Whoever reaches its port can read and change every dataset, run
  models on your OpenRouter key, and read and write the server's files. It listens on `127.0.0.1` by
  default, and the Compose file publishes it on `127.0.0.1` only; keep it that way, and use hosted
  mode for anything shared.
- **Hosted mode** signs everyone in with WorkOS, keeps each organisation's data to itself, refuses
  the server's own files and private addresses, and encrypts saved keys with `ROWLAB_SECRET_KEY`. It
  still expects a proxy or tunnel with TLS and rate limits in front, Postgres and S3 on a private
  network, and private addresses (other than those two) blocked in the network as well. See
  [A shared server](https://docs.rowlab.dev/self-host/hosted).
- **Rows go to models.** A run sends the prompt with each row's columns to the models it uses,
  through OpenRouter. Their answers are data: they are written to columns and never executed.
- **Agents act as you.** An MCP client or API key has the rights of the person it belongs to.
