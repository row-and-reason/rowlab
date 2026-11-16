import sys

from rowlab import cli
from rowlab.core import serving


def test_rowlab_alone_serves(monkeypatch):
    served = []
    monkeypatch.setattr(serving.Server, "run", lambda self: served.append(self.config))
    monkeypatch.setattr(sys, "argv", ["rowlab"])
    cli.main()
    [config] = served
    assert (config.app, config.host, config.port) == ("rowlab.app:app", "127.0.0.1", 8000)
