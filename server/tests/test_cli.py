import sys

import pytest
import uvicorn

from rowlab import __version__, cli


def test_rowlab_alone_serves(monkeypatch):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, "argv", ["rowlab"])
    cli.main()
    assert calls == [(("rowlab.app:app",), {"host": "127.0.0.1", "port": 8000, "reload": False})]


def test_version(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["rowlab", "--version"])
    with pytest.raises(SystemExit):
        cli.main()
    assert capsys.readouterr().out == f"rowlab {__version__}\n"
