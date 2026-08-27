"""Tests for the package command-line interface."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch
from typer.testing import CliRunner

from whep_digitize import cli


def test_cli_without_subcommand_runs_pipeline(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[bool, str | None]] = []

    def fake_run_pipeline(*, show_view: bool = False, dataset_name: str | None = None) -> None:
        calls.append((show_view, dataset_name))

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = CliRunner().invoke(cli.app, [])

    assert result.exit_code == 0
    assert calls == [(False, None)]


def test_cli_without_subcommand_passes_options(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[bool, str | None]] = []

    def fake_run_pipeline(*, show_view: bool = False, dataset_name: str | None = None) -> None:
        calls.append((show_view, dataset_name))

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = CliRunner().invoke(cli.app, ["--show-view", "--dataset", "FAO 1955"])

    assert result.exit_code == 0
    assert calls == [(True, "FAO 1955")]


def test_cli_bootstrap_does_not_run_default_pipeline(monkeypatch: MonkeyPatch) -> None:
    def fail_run_pipeline(*, show_view: bool = False, dataset_name: str | None = None) -> None:
        _ = (show_view, dataset_name)
        raise AssertionError("default pipeline should not run for subcommands")

    def fake_run_setup_pipeline(dataset_name: str | None = None) -> SimpleNamespace:
        _ = dataset_name
        return SimpleNamespace(
            dataset_name="whep_data_raw",
            project_root=Path("project"),
            paths=SimpleNamespace(
                data=SimpleNamespace(
                    import_=SimpleNamespace(raw=Path("data/import/raw")),
                    audit=SimpleNamespace(audit_dir=Path("data/postpro/audit")),
                    export=SimpleNamespace(processed=Path("data/export/processed_data")),
                )
            ),
        )

    monkeypatch.setattr(cli, "run_pipeline", fail_run_pipeline)
    monkeypatch.setattr(cli, "run_setup_pipeline", fake_run_setup_pipeline)
    result = CliRunner().invoke(cli.app, ["bootstrap"])

    assert result.exit_code == 0
