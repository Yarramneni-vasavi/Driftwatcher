"""Driftwatch CLI: scan | map | check | fix + config | llm | logs.

Plan sec. 10. Global flags on every command: --config, --profile,
--model, -v/-vv, --log-format, --quiet. Exit codes: 0 pass or
warn-only; 1 contradiction in an `enforced` feature; 2 tool error.
`make drift` wraps `check --base origin/main`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..agents.non_llm import (
    context_scanner,
    mapping_store,
    reporter,
    rule_checker,
    rule_claims,
)
from ..config import loader as config_loader
from ..contracts.claims import DocText
from ..contracts.context import ScanRequest
from ..contracts.verdicts import Verdict
from ..llm import client as llm_client
from ..llm.budget import Budget
from ..observability import viewer as log_viewer
from ..observability.logger import StepLogger, end_run, init_run
from ..orchestrator import check as check_flow
from ..orchestrator import fix as fix_flow
from ..orchestrator import onboard as onboard_flow
from ..orchestrator.bus import new_correlation_id
from .render import print_report

app = typer.Typer(name="driftwatch", help="Detect drift between docs and code.")
config_app = typer.Typer(help="Inspect resolved configuration.")
llm_app = typer.Typer(help="Test LLM provider profiles.")
app.add_typer(config_app, name="config")
app.add_typer(llm_app, name="llm")

ConfigOpt = Annotated[
    Optional[str], typer.Option("--config", is_flag=False, help="Path to driftwatch.config.yaml.")
]
ProfileOpt = Annotated[
    Optional[str], typer.Option("--profile", is_flag=False, help="LLM profile to use.")
]
ModelOpt = Annotated[
    Optional[str], typer.Option("--model", is_flag=False, help="Override the profile's model.")
]
VerboseOpt = Annotated[
    bool, typer.Option("-v", "--verbose", help="Enable DEBUG logging.")
]
VeryVerboseOpt = Annotated[
    bool, typer.Option("-vv", help="Enable TRACE logging.")
]
LogFormatOpt = Annotated[
    Optional[str],
    typer.Option("--log-format", is_flag=False, help="Console format: pretty|plain|json."),
]
QuietOpt = Annotated[
    bool, typer.Option("--quiet", help="Disable console log output.")
]
RepoOpt = Annotated[str, typer.Option("--repo", is_flag=False, help="Repo root.")]


def _level_for(verbosity: int) -> str | None:
    if verbosity >= 2:
        return "TRACE"
    if verbosity == 1:
        return "DEBUG"
    return None


def _verbosity(verbose: bool, very_verbose: bool) -> int:
    """Convert the separate CLI flags to the historical 0/1/2 level."""
    if very_verbose:
        return 2
    return 1 if verbose else 0


def _setup(
    command: str,
    summary: str,
    repo: str,
    config: str | None,
    profile: str | None,
    model: str | None,
    verbose: int,
    log_format: str | None,
    quiet: bool,
) -> tuple[Budget, str, StepLogger]:
    if log_format is not None and log_format not in ("pretty", "plain", "json"):
        typer.echo("error: --log-format must be pretty|plain|json", err=True)
        raise typer.Exit(code=2)
    try:
        cfg, _sources = config_loader.load(
            config_path=config,
            profile=profile,
            model=model,
            log_level=_level_for(verbose),
            log_format=log_format,
            quiet=quiet,
            repo_root=repo,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    budget = Budget.from_config(cfg)
    run_id = f"run-{new_correlation_id()}"
    logger, _ctx = init_run(
        cfg, run_id, command, repo_root=repo, budget=budget
    )
    logger.run_start(f"{command} {summary}".strip())
    return budget, run_id, logger


def _finish(logger: StepLogger, message: str) -> None:
    logger.run_end(message)
    end_run()


@app.command()
def scan(
    repo: RepoOpt = ".",
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    model: ModelOpt = None,
    verbose: VerboseOpt = False,
    very_verbose: VeryVerboseOpt = False,
    log_format: LogFormatOpt = None,
    quiet: QuietOpt = False,
) -> None:
    _budget, run_id, logger = _setup(
        "scan", f"repo={repo}", repo, config, profile, model,
        _verbosity(verbose, very_verbose), log_format, quiet,
    )
    try:
        cfg = config_loader.get_active()
        inv = context_scanner.scan(
            ScanRequest(repo_root=repo, deny_globs=cfg.scan.deny_globs),
            known_names=set(cfg.scan.known_context_names),
        )
        print(f"Found {len(inv.files)} context files.")
        verdicts: list[Verdict] = []
        for index, doc in enumerate(inv.files, start=1):
            p = Path(repo) / doc.path
            if not p.exists():
                logger.step_skip("scan", f"{doc.path} missing")
                continue
            logger.step_start(
                "scan",
                {"doc": doc.path, "index": index, "total": len(inv.files)},
            )
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            checked = 0
            for claim in rule_claims.extract(
                DocText(doc_path=doc.path, lines=lines)
            ).claims:
                result = rule_checker.check(claim, repo, "")
                if isinstance(result, Verdict):
                    verdicts.append(result)
                checked += 1
            logger.step_end("scan", {"doc": doc.path, "claims": checked})
        for verdict in verdicts:
            ev = ", ".join(f"{e.file}:{e.line}" for e in verdict.evidence) or "-"
            print(f"[{verdict.verdict}] {verdict.claim_id} {ev} {verdict.reason}")
        _finish(logger, f"{run_id} done files={len(inv.files)}")
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        end_run()
        raise typer.Exit(code=2) from exc


@app.command(name="map")
def map_cmd(
    repo: RepoOpt = ".",
    feature: Annotated[
        Optional[str], typer.Option("--feature", is_flag=False, help="Onboard one feature only.")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Skip prompts.")] = False,
    features: Annotated[
        Optional[str], typer.Option("--features", is_flag=False, help="Human-written features file (skips scout+confirm).")
    ] = None,
    propose: Annotated[bool, typer.Option("--propose", help="Print scout proposal as a features file.")] = False,
    refresh: Annotated[bool, typer.Option("--refresh", help="Re-run discovery for auto fields.")] = False,
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    model: ModelOpt = None,
    verbose: VerboseOpt = False,
    very_verbose: VeryVerboseOpt = False,
    log_format: LogFormatOpt = None,
    quiet: QuietOpt = False,
) -> None:
    _budget, run_id, logger = _setup(
        "map", f"repo={repo}", repo, config, profile, model,
        _verbosity(verbose, very_verbose), log_format, quiet,
    )
    try:
        if propose and features:
            typer.echo("error: --propose cannot be combined with --features", err=True)
            end_run()
            raise typer.Exit(code=2)
        if refresh and not features:
            typer.echo("error: --refresh requires --features", err=True)
            end_run()
            raise typer.Exit(code=2)
        if propose:
            import json as _json

            print(_json.dumps(onboard_flow.propose_features(repo_root=repo), indent=2))
            _finish(logger, f"{run_id} done propose")
            return
        mapping = onboard_flow.run_onboard(
            repo_root=repo, feature=feature, yes=yes,
            features_path=features, refresh=refresh,
        )
        print(f"Mapped {len(mapping.features)} features to {mapping_store.FILENAME}.")
        _finish(logger, f"{run_id} done features={len(mapping.features)}")
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        end_run()
        raise typer.Exit(code=2) from exc


@app.command()
def check(
    base: Annotated[str, typer.Option("--base", is_flag=False, help="Diff base ref (committed scope only).")] = "origin/main",
    scope: Annotated[str, typer.Option("--scope", is_flag=False, help="committed|uncommitted|full|partial.")] = "committed",
    path: Annotated[
        Optional[str], typer.Option("--path", is_flag=False, help="Folder for partial scope.")
    ] = None,
    mode: Annotated[
        Optional[str], typer.Option("--mode", is_flag=False, help="warn|enforce (default from config).")
    ] = None,
    engine: Annotated[
        Optional[str], typer.Option("--engine", is_flag=False, help="legacy|flow (flow = B3+B4 miner + whole-doc missing pass).")
    ] = None,
    repo: RepoOpt = ".",
    out: Annotated[
        Optional[str], typer.Option("--out", is_flag=False, help="Write Markdown report to file.")
    ] = None,
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    model: ModelOpt = None,
    verbose: VerboseOpt = False,
    very_verbose: VeryVerboseOpt = False,
    log_format: LogFormatOpt = None,
    quiet: QuietOpt = False,
) -> None:
    budget, run_id, logger = _setup(
        "check", f"base={base}", repo, config, profile, model,
        _verbosity(verbose, very_verbose), log_format, quiet,
    )
    resolved_mode = mode or config_loader.get_active().check.default_mode
    if resolved_mode not in ("warn", "enforce"):
        typer.echo("error: --mode must be warn|enforce", err=True)
        end_run()
        raise typer.Exit(code=2)
    if scope not in ("committed", "uncommitted", "full", "partial"):
        typer.echo("error: --scope must be committed|uncommitted|full|partial", err=True)
        end_run()
        raise typer.Exit(code=2)
    if scope == "partial" and not path:
        typer.echo("error: --scope partial requires --path <folder>", err=True)
        end_run()
        raise typer.Exit(code=2)
    if path and scope != "partial":
        typer.echo("error: --path only applies to --scope partial", err=True)
        end_run()
        raise typer.Exit(code=2)
    if base != "origin/main" and scope != "committed":
        typer.echo("error: --base only applies to --scope committed", err=True)
        end_run()
        raise typer.Exit(code=2)
    resolved_engine = engine or "legacy"
    if resolved_engine not in ("legacy", "flow"):
        typer.echo("error: --engine must be legacy|flow", err=True)
        end_run()
        raise typer.Exit(code=2)
    try:
        report = check_flow.run_check(
            repo_root=repo, base=base, mode=resolved_mode, budget=budget,
            scope=scope, path=path, engine=resolved_engine,
        )
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        end_run()
        raise typer.Exit(code=2) from exc
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        end_run()
        raise typer.Exit(code=2) from exc
    print_report(report)
    markdown = reporter.render_markdown(report)
    if out:
        Path(out).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    code = reporter.exit_code(report)
    _finish(logger, f"{run_id} done contradicted={report.contradicted} exit={code}")
    raise typer.Exit(code=code)


@app.command()
def fix(
    pr: Annotated[
        Optional[int], typer.Option("--pr", is_flag=False, help="Read report from MR comments.")
    ] = None,
    repo: RepoOpt = ".",
    base: Annotated[str, typer.Option("--base", is_flag=False, help="Diff base ref.")] = "origin/main",
    yes: Annotated[bool, typer.Option("--yes", help="Skip prompts.")] = False,
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    model: ModelOpt = None,
    verbose: VerboseOpt = False,
    very_verbose: VeryVerboseOpt = False,
    log_format: LogFormatOpt = None,
    quiet: QuietOpt = False,
) -> None:
    _budget, run_id, logger = _setup(
        "fix", f"repo={repo}", repo, config, profile, model,
        _verbosity(verbose, very_verbose), log_format, quiet,
    )
    try:
        report = fix_flow.run_fix(repo_root=repo, pr=pr, base=base, yes=yes)
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        end_run()
        raise typer.Exit(code=2) from exc
    print_report(report)
    code = reporter.exit_code(report)
    _finish(logger, f"{run_id} done contradicted={report.contradicted} exit={code}")
    raise typer.Exit(code=code)


@config_app.command("show")
def config_show(
    repo: RepoOpt = ".",
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    model: ModelOpt = None,
    verbose: VerboseOpt = False,
    very_verbose: VeryVerboseOpt = False,
    log_format: LogFormatOpt = None,
    quiet: QuietOpt = False,
) -> None:
    try:
        cfg, sources = config_loader.load(
            config_path=config,
            profile=profile,
            model=model,
            log_level=_level_for(_verbosity(verbose, very_verbose)) or None,
            log_format=log_format,
            quiet=quiet,
            repo_root=repo,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    print(json.dumps(config_loader.redacted_view(cfg), indent=2))
    if sources:
        print("sources:")
        for field, source in sorted(sources.items()):
            print(f"  {field}: {source}")


@llm_app.command("ping")
def llm_ping(
    profile: Annotated[
        Optional[str], typer.Option("--profile", is_flag=False, help="Profile to test.")
    ] = None,
    repo: RepoOpt = ".",
    config: ConfigOpt = None,
    model: ModelOpt = None,
    verbose: VerboseOpt = False,
    very_verbose: VeryVerboseOpt = False,
    log_format: LogFormatOpt = None,
    quiet: QuietOpt = False,
) -> None:
    _budget, run_id, logger = _setup(
        "llm ping", f"profile={profile or 'default'}", repo, config,
        profile, model, _verbosity(verbose, very_verbose), log_format, quiet,
    )
    try:
        result = llm_client.ping(profile_name=profile)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"error: {exc}", err=True)
        end_run()
        raise typer.Exit(code=2) from exc
    print(
        f"ok provider={result['provider']} model={result['model']} "
        f"latency={result['latency_ms']}ms mode={result['mode']}"
    )
    _finish(logger, f"{run_id} done profile={result['provider']}")
    raise typer.Exit(code=0 if result["ok"] else 2)


@app.command()
def logs(
    run: Annotated[str, typer.Option("--run", is_flag=False, help="Run id or 'latest'.")] = "latest",
    agent: Annotated[
        Optional[str], typer.Option("--agent", is_flag=False, help="Filter by agent id.")
    ] = None,
    feature: Annotated[
        Optional[str], typer.Option("--feature", is_flag=False, help="Filter by feature.")
    ] = None,
    level: Annotated[str, typer.Option("--level", is_flag=False, help="Minimum level.")] = "INFO",
    follow: Annotated[bool, typer.Option("--follow", help="Tail the file.")] = False,
    repo: RepoOpt = ".",
    format: Annotated[str, typer.Option("--format", is_flag=False, help="pretty|plain|json.")] = "pretty",
) -> None:
    path = log_viewer.resolve_run_file(repo, run)
    if path is None:
        typer.echo(f"error: no log found for run {run!r}", err=True)
        raise typer.Exit(code=2)
    if follow:
        import time

        print(log_viewer.render(
            log_viewer.filter_events(
                log_viewer.read_events(path), agent, feature, level
            ),
            format,
        ))
        with open(path, encoding="utf-8") as handle:
            handle.seek(0, 2)
            try:
                while True:
                    line = handle.readline()
                    if line.strip():
                        events = log_viewer.filter_events(
                            [json.loads(line)], agent, feature, level
                        )
                        if events:
                            print(log_viewer.render(events, format))
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        return
    events = log_viewer.filter_events(
        log_viewer.read_events(path), agent, feature, level
    )
    print(log_viewer.render(events, format))


if __name__ == "__main__":
    app()
