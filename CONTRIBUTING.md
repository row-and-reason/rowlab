# Contributing

Thanks for helping. Bug reports, docs fixes and pull requests are all welcome.

- **Bugs and ideas:** open an [issue](https://github.com/row-and-reason/rowlab/issues). For anything
  bigger than a fix, say what you have in mind in an issue first, so no work is wasted.
- **Security problems:** not in an issue; see [SECURITY.md](SECURITY.md).

## Making a change

The [README](README.md#development) has the setup. [AGENTS.md](AGENTS.md) is how code is written
here, for people and agents alike: simple, boring code, logic in `server/src/rowlab/core/`, shadcn
for the UI, and cleaning up as you go.

Before opening a pull request:

```sh
make lint test    # and `make test-hosted` if you touched the database or storage
make gen-client   # after any API change: openapi.json and the web client must match it
make smoke        # if you touched packaging or startup: end to end against the built wheel
```

Update the docs in `site/docs/` when behaviour changes; [site/README.md](site/README.md) says how.

## Sign off your commits

rowlab uses the [Developer Certificate of Origin](https://developercertificate.org): by signing off
a commit, you certify that you wrote it or otherwise have the right to contribute it under the
project's license. Sign off with `git commit -s`, which adds a line with your name and email:

```
Signed-off-by: Ada Lovelace <ada@example.com>
```

A check on every pull request asks for it on each commit. Forgot? `git rebase --signoff main` and
force-push.

Contributions are licensed under [Apache-2.0](LICENSE), like the rest of rowlab. Everyone taking
part follows the [code of conduct](CODE_OF_CONDUCT.md).
