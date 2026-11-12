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
make check        # lint, test, build (which regenerates openapi.json and the web client), site
make test-hosted  # if you touched the database or storage
make smoke        # if you touched packaging or startup: end to end against the built wheel
```

Update the docs in `site/docs/` when behaviour changes; [site/README.md](site/README.md) says how.

## Releasing

Maintainers set `version` in `server/pyproject.toml`, merge, and push a matching tag from `main`:
`git tag v0.2.0 && git push origin v0.2.0`. The Publish workflow then builds the images as `0.2.0`
and `latest`, and publishes the package, with the web UI inside, to
[PyPI](https://pypi.org/project/rowlab/) through trusted publishing. It refuses a tag that doesn't
match the version.

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
