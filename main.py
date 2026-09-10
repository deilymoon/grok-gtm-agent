#!/usr/bin/env python3
"""Grok GTM Agent — CLI entrypoint. Progressive Rich terminal UX."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from agent import run_pipeline, save_leads, save_outputs
from config import load_config
from models import Company, GTMResult, Opportunity
from research import load_demo_companies
from scoring import compute_gtm_score

DEFAULT_PRODUCT = "AI support automation for B2B SaaS"

SIGNAL_LABEL = {
    "hiring": "HIRING",
    "department_hire": "HIRING",
    "leadership_hire": "NEW ROLE",
    "funding": "FUNDING",
    "enterprise_expansion": "EXPANSION",
    "market_expansion": "EXPANSION",
    "product_launch": "LAUNCH",
    "migration": "MIGRATION",
    "growth": "GROWTH",
    "competitor": "COMPETITOR",
    "complaints": "COMPLAINTS",
    "bottleneck": "BOTTLENECK",
    "problem_discussion": "PROBLEM",
}

console = Console()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Grok GTM Agent — find companies ready to buy (CLI).",
    )
    p.add_argument(
        "product",
        nargs="?",
        default=None,
        help="Short product description. Interactive prompt if omitted.",
    )
    p.add_argument(
        "--product",
        dest="product_flag",
        default=None,
        help="Product description (alternative to positional arg).",
    )
    p.add_argument(
        "--mode",
        choices=["demo", "live"],
        default=None,
        help="demo (offline dataset) or live (xAI Grok API). Overrides MODE env.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max candidates to research in live mode (default 15).",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Path for leads.json (default output/leads.json).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose status logging.",
    )
    p.add_argument(
        "--no-hold",
        action="store_true",
        help="Exit immediately after run (default: hold for Enter).",
    )
    return p.parse_args(argv)


def bar(score: float, width: int = 10) -> str:
    filled = int(round((score / 100.0) * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def signal_tag(sig_type: str) -> str:
    return SIGNAL_LABEL.get(sig_type, sig_type.replace("_", " ").upper()[:10])


def boost_points(strength: float) -> int:
    return max(8, min(22, int(round(8 + strength * 14))))


@dataclass
class SignalEvent:
    stamp: str
    tag: str
    company: str
    points: int


@dataclass
class DemoState:
    stage: str = ""
    icp_lines: list[str] = field(default_factory=list)
    scan_line: str = ""
    stream: list[SignalEvent] = field(default_factory=list)
    accounts: int = 0
    icp_matches: int = 0
    signals: int = 0
    high_intent: int = 0
    analyze_lines: list[str] = field(default_factory=list)
    score_rows: list[tuple[str, float]] = field(default_factory=list)
    status: str = ""


def render_header(product: str, mode: str) -> Group:
    mode_label = "DEMO MODE" if mode == "demo" else "LIVE MODE"
    title = Text()
    title.append("GROK GTM AGENT", style="bold white")
    title.append("\n")
    title.append("Signal-based company discovery", style="dim")
    title.append("\n")
    title.append(mode_label, style="bold yellow")
    prod = Text()
    prod.append("PRODUCT\n", style="bold")
    prod.append(product)
    return Group(
        Rule(style="bright_black"),
        title,
        Rule(style="bright_black"),
        Text(""),
        prod,
        Text(""),
        Rule(style="bright_black"),
    )


def render_counters(state: DemoState) -> Table:
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 0), expand=False)
    t.add_column(style="dim", width=14)
    t.add_column(justify="right", style="bold cyan", width=4)
    t.add_row("ACCOUNTS", str(state.accounts))
    t.add_row("ICP MATCHES", str(state.icp_matches))
    t.add_row("SIGNALS", str(state.signals))
    t.add_row("HIGH INTENT", str(state.high_intent))
    return t


def render_stream(state: DemoState) -> Group:
    lines: list[Text] = []
    for ev in state.stream[-8:]:
        line = Text()
        line.append(ev.stamp, style="dim")
        line.append("  ")
        line.append(f"{ev.tag:<10}", style="bold green")
        line.append("  ")
        line.append(f"{ev.company:<12}")
        line.append("  ")
        line.append(f"+{ev.points}", style="bold yellow")
        lines.append(line)
    if not lines:
        lines.append(Text("waiting for signals…", style="dim"))
    return Group(*lines)


def render_frame(product: str, mode: str, state: DemoState) -> Group:
    parts: list = [render_header(product, mode), Text("")]

    if state.stage:
        parts.append(Text(state.stage, style="bold cyan"))
        parts.append(Text(""))

    if state.icp_lines:
        for ln in state.icp_lines:
            parts.append(Text(f"  ✓  {ln}"))
        parts.append(Text(""))

    if state.scan_line:
        parts.append(Text(f"  {state.scan_line}"))
        parts.append(Text(""))

    if state.stream or state.accounts:
        grid = Table(show_header=False, box=None, expand=True, padding=(0, 2, 0, 0))
        grid.add_column(ratio=1)
        grid.add_column(ratio=2)
        left = Group(Text("COUNTERS", style="bold dim"), render_counters(state))
        right = Group(Text("LIVE SIGNAL STREAM", style="bold dim"), render_stream(state))
        grid.add_row(left, right)
        parts.append(grid)
        parts.append(Text(""))

    if state.analyze_lines:
        for ln in state.analyze_lines:
            parts.append(Text(f"  {ln}"))
        parts.append(Text(""))

    if state.score_rows:
        for name, score in state.score_rows:
            row = Text()
            row.append(f"  {name:<12}")
            row.append(f" {bar(score)} ", style="cyan")
            row.append(f"{int(score):>3}", style="bold")
            parts.append(row)
        parts.append(Text(""))

    if state.status:
        parts.append(Text(state.status, style="dim"))

    return Group(*parts)


def hold_screen(no_hold: bool) -> None:
    if no_hold:
        return
    console.print()
    console.print(Rule(style="bright_black"))
    console.print("[dim]Demo complete — press Enter to exit[/dim]")
    try:
        input()
    except EOFError:
        time.sleep(120)


def render_opportunity_detail(opp: Opportunity, rank: int, large: bool) -> Group:
    comps = (opp.score_breakdown or {}).get("components", {})
    title = Text()
    title.append(f"#{rank:02d}  {opp.company.upper()}", style="bold white")
    if opp.website:
        title.append(f"   {opp.website}", style="dim")
    title.append(f"\nGTM SCORE  {int(opp.gtm_score)}/100", style="bold yellow")

    metrics = Table(show_header=False, box=None, padding=(0, 3, 0, 0))
    metrics.add_column(style="dim", width=18)
    metrics.add_column(justify="right", style="bold", width=6)
    metrics.add_row("ICP FIT", f"{comps.get('icp_fit', opp.icp_fit):.0f}")
    metrics.add_row("SIGNAL STRENGTH", f"{comps.get('signal_strength', opp.signal_score):.0f}")
    metrics.add_row("FRESHNESS", f"{comps.get('signal_freshness', 0):.0f}")
    metrics.add_row("TIMING", f"{comps.get('timing', opp.timing_score):.0f}")

    body: list = [title, Text(""), metrics, Text("")]

    body.append(Text("SIGNALS", style="bold"))
    for s in opp.signals[:4]:
        body.append(Text(f"  ✓  {s}"))
    body.append(Text(""))

    if large:
        body.append(Text("WHY NOW", style="bold"))
        body.append(Text(f"  {opp.why_now}"))
        body.append(Text(""))
        body.append(Text("BEST CONTACT", style="bold"))
        body.append(Text(f"  {opp.best_contact_role}"))
        body.append(Text(""))
        body.append(Text("ANGLE", style="bold"))
        body.append(Text(f"  {opp.outreach_angle}"))
        body.append(Text(""))
        body.append(Text("OUTREACH", style="bold"))
        body.append(Panel(opp.outreach_message, border_style="bright_black", expand=False))
        body.append(Text("ACTION: CONTACT NOW", style="bold yellow"))

    return Group(
        Panel(
            Group(*body),
            border_style="white" if large else "bright_black",
            expand=False,
        )
    )


def render_compact_opp(opp: Opportunity, rank: int) -> Text:
    t = Text()
    t.append(f"  #{rank:02d}  ", style="bold")
    t.append(f"{opp.company:<14}")
    t.append(f" {bar(opp.gtm_score, 8)} ", style="cyan")
    t.append(f"{int(opp.gtm_score)}/100", style="bold")
    contact = opp.best_contact_role or ""
    if contact:
        t.append(f"   {contact}", style="dim")
    return t


def run_demo_ui(product: str, result: GTMResult, companies: list[Company], no_hold: bool) -> int:
    ranked_all: list[tuple[Company, float, dict]] = []
    for co in companies:
        bd = compute_gtm_score(co, result.product, result.icp)
        ranked_all.append((co, float(bd["gtm_score"]), bd))
    ranked_all.sort(key=lambda x: x[1], reverse=True)

    state = DemoState()
    clock = datetime.now().replace(microsecond=0)

    def tick(seconds: float = 0.0) -> str:
        nonlocal clock
        if seconds:
            clock = clock + timedelta(seconds=seconds)
        return clock.strftime("%H:%M:%S")

    with Live(
        render_frame(product, result.mode, state),
        console=console,
        refresh_per_second=12,
        transient=False,
    ) as live:
        def paint() -> None:
            live.update(render_frame(product, result.mode, state))

        state.stage = "[01] BUILDING ICP"
        paint()
        time.sleep(0.7)

        icp = result.icp
        checks = [
            icp.industry or "B2B SaaS",
            icp.company_size or "20–500 employees",
            " / ".join(icp.markets) if icp.markets else "US / Europe",
            icp.target_team or "Growing support teams",
        ]
        if checks[3] and "support" in checks[3].lower():
            checks[3] = "Growing support teams"
        for c in checks:
            state.icp_lines.append(c)
            paint()
            time.sleep(0.65)

        time.sleep(0.4)
        state.icp_lines = list(state.icp_lines)
        state.icp_lines = [f"{x}" for x in checks]
        time.sleep(0.3)

        state.stage = "[02] SCANNING ACCOUNTS"
        state.accounts = len(companies)
        paint()
        time.sleep(0.5)

        pending_events: list[tuple[int, Company, object]] = []
        for idx, co in enumerate(companies):
            for sig in co.signals:
                pending_events.append((idx, co, sig))

        high_names = {o.company for o in result.opportunities}
        for i, co in enumerate(companies, 1):
            state.scan_line = f"Analyzing {i:02d}/{len(companies):02d}  {co.name}"
            score = next(s for c, s, _ in ranked_all if c.name == co.name)
            if score >= 75:
                state.icp_matches = min(len(companies), state.icp_matches + 1)
            paint()
            time.sleep(0.58)

            if co.signals:
                sig = max(co.signals, key=lambda s: s.strength)
                stamp = tick(0.85)
                pts = boost_points(sig.strength)
                state.stream.append(
                    SignalEvent(stamp, signal_tag(sig.type), co.name, pts)
                )
                state.signals += 1
                state.signals += max(0, len(co.signals) - 1)
                paint()
                time.sleep(0.42)

            if co.name in high_names:
                state.high_intent = min(5, state.high_intent + 1)
                paint()

        state.scan_line = f"Scan complete · {len(companies)} accounts"
        state.high_intent = len(result.opportunities)
        paint()
        time.sleep(0.7)

        state.stage = "[03] ANALYZING SIGNALS"
        state.scan_line = ""
        state.analyze_lines = []
        paint()
        time.sleep(0.35)

        seen: set[str] = set()
        for opp in result.opportunities:
            for s in opp.signals:
                tag = s.split(":")[0].strip()
                if tag in seen:
                    continue
                seen.add(tag)
                label = signal_tag(tag)
                state.analyze_lines.append(f"Evaluating {label:<10} · relevance check")
                paint()
                time.sleep(0.4)
                state.analyze_lines[-1] = f"Evaluating {label:<10} · keep"
                paint()
                time.sleep(0.25)
                if len(seen) >= 6:
                    break
            if len(seen) >= 6:
                break

        time.sleep(0.4)

        state.stage = "[04] SCORING OPPORTUNITIES"
        state.analyze_lines = []
        state.score_rows = []
        paint()
        time.sleep(0.35)

        for opp in result.opportunities:
            target = opp.gtm_score
            for step in (40, 65, 85, target):
                names = [n for n, _ in state.score_rows]
                if opp.company in names:
                    state.score_rows = [
                        (n, (step if n == opp.company else sc))
                        for n, sc in state.score_rows
                    ]
                else:
                    state.score_rows.append((opp.company, float(step)))
                paint()
                time.sleep(0.12)
            time.sleep(0.2)

        time.sleep(0.6)
        state.status = "Ranking complete · revealing top opportunities"
        paint()
        time.sleep(0.8)

    console.print()
    console.print(Rule("[bold]TOP OPPORTUNITIES[/bold]", style="white"))
    console.print()
    time.sleep(0.35)

    top = result.opportunities
    if top:
        console.print(render_opportunity_detail(top[0], 1, large=True))
        console.print()
        time.sleep(0.7)
        if len(top) > 1:
            console.print(Text("ALSO RANKED", style="bold dim"))
            for i, opp in enumerate(top[1:], 2):
                console.print(render_compact_opp(opp, i))
                time.sleep(0.25)
            console.print()

    cfg_out = load_config(mode_override=result.mode)
    leads_path, run_path = save_outputs(result, cfg_out.output_path)
    console.print(
        f"[dim]Saved {leads_path} · {result.mode.upper()} · {len(top)} opportunities[/dim]"
    )
    console.print(f"[dim]Run file {run_path}[/dim]")
    hold_screen(no_hold)
    return 0


def run_live_ui(
    product: str,
    mode: Optional[str],
    no_hold: bool,
    *,
    limit: Optional[int] = None,
    output: Optional[str] = None,
    verbose: bool = False,
) -> int:
    cfg = load_config(
        mode_override=mode,
        output_override=output,
        limit=limit,
        verbose=verbose,
    )
    console.print(render_header(product, cfg.mode))
    console.print()
    console.print("[bold]LIVE research via xAI web_search + x_search[/bold]")
    console.print(f"[dim]model={cfg.model}  limit={cfg.research_limit}[/dim]")
    console.print()

    def live_progress(msg: str) -> None:
        console.print(f"  {msg}")

    try:
        result = run_pipeline(product, cfg, progress=live_progress)
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[bold red]LIVE failed:[/bold red] {exc}")
        return 1

    console.print()
    icp = result.icp
    console.print("[bold]ICP[/bold]")
    console.print(f"  {icp.industry} · {icp.company_size} · {' / '.join(icp.markets)}")
    console.print(f"  Team: {icp.target_team}")
    if icp.summary:
        console.print(f"  [dim]{icp.summary[:240]}{'…' if len(icp.summary) > 240 else ''}[/dim]")

    console.print()
    console.print(Rule("[bold]TOP OPPORTUNITIES[/bold]", style="white"))
    console.print()
    if not result.opportunities:
        console.print("[yellow]No evidence-backed opportunities found.[/yellow]")
        return 1

    console.print(render_opportunity_detail(result.opportunities[0], 1, large=True))
    console.print()
    for i, opp in enumerate(result.opportunities[1:], 2):
        console.print(render_compact_opp(opp, i))
        if verbose:
            for src in opp.sources[:3]:
                console.print(f"      [dim]{src}[/dim]")

    leads_path, run_path = save_outputs(result, cfg.output_path)
    console.print()
    console.print(f"[dim]Saved {leads_path}[/dim]")
    console.print(f"[dim]Run file {run_path}[/dim]")
    hold_screen(no_hold)
    return 0


def run_ui(
    product: str,
    mode: Optional[str],
    no_hold: bool = False,
    *,
    limit: Optional[int] = None,
    output: Optional[str] = None,
    verbose: bool = False,
) -> int:
    cfg = load_config(
        mode_override=mode,
        output_override=output,
        limit=limit,
        verbose=verbose,
    )
    if cfg.mode == "live":
        return run_live_ui(
            product,
            mode,
            no_hold,
            limit=limit,
            output=output,
            verbose=verbose,
        )

    result = run_pipeline(product, cfg, progress=lambda _: None)
    companies = load_demo_companies(cfg.demo_dir)
    return run_demo_ui(product, result, companies, no_hold)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    product = args.product_flag or args.product
    if not product:
        if sys.stdin.isatty() and not args.mode:
            console.print("[bold]Enter product description[/bold] (or press Enter for default):")
            try:
                line = input("> ").strip()
            except EOFError:
                line = ""
            product = line or DEFAULT_PRODUCT
        else:
            product = DEFAULT_PRODUCT
    if product.startswith("AI tool that automates") and (args.mode or "demo") != "live":
        product = DEFAULT_PRODUCT
    try:
        return run_ui(
            product,
            args.mode,
            no_hold=args.no_hold,
            limit=args.limit,
            output=args.output,
            verbose=args.verbose,
        )
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
