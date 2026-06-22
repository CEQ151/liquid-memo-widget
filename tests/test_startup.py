"""Tests for launch-at-login reconciliation. The real HKCU\\...\\Run value is never read or
written here — the registry helpers and the `frozen` flag are monkeypatched, so set_startup
(the only thing that would mutate the registry) is replaced with a recorder."""
import startup


def _patch(monkeypatch, *, frozen=True, current=None, desired='"C:/App/App.exe"'):
    """Wire startup's registry seams to in-memory stand-ins and record set_startup calls."""
    monkeypatch.setattr(startup.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(startup, "_read_startup_command", lambda: current)
    monkeypatch.setattr(startup, "_command", lambda: desired)
    calls: list[bool] = []
    monkeypatch.setattr(startup, "set_startup", lambda enabled: calls.append(enabled))
    return calls


def test_reconcile_repoints_when_path_drifted(monkeypatch):
    # A portable build had claimed auto-start; the installed build now runs and re-claims it.
    calls = _patch(monkeypatch, current='"D:/Portable/App.exe"', desired='"C:/App/App.exe"')
    startup.reconcile_startup()
    assert calls == [True]


def test_reconcile_noop_when_already_current(monkeypatch):
    calls = _patch(monkeypatch, current='"C:/App/App.exe"', desired='"C:/App/App.exe"')
    startup.reconcile_startup()
    assert calls == []  # value already points at us — no needless registry write


def test_reconcile_noop_when_autostart_disabled(monkeypatch):
    calls = _patch(monkeypatch, current=None)  # no Run value -> auto-start is off
    startup.reconcile_startup()
    assert calls == []  # must not enable auto-start the user never turned on


def test_reconcile_skips_unfrozen_source_run(monkeypatch):
    # A dev/source run must never hijack a real install's entry, and shouldn't even read it.
    reads: list[str] = []
    monkeypatch.setattr(startup.sys, "frozen", False, raising=False)
    monkeypatch.setattr(startup, "_read_startup_command", lambda: reads.append("read"))
    calls: list[bool] = []
    monkeypatch.setattr(startup, "set_startup", lambda enabled: calls.append(enabled))
    startup.reconcile_startup()
    assert reads == [] and calls == []
