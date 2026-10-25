import os
import argparse
import json
import sys
from pathlib import Path
from .storage import Store
from .engine import scan, DEFAULTS
from .exporting import export
from . import imports


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="nicktrail", description="NickTrail — local public-footprint audit")
    p.add_argument("--db", default="nicktrail.sqlite3")
    sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("create")
    x.add_argument("name")
    sub.add_parser("projects")
    x = sub.add_parser("add")
    x.add_argument("project", type=int)
    x.add_argument("value")
    x.add_argument(
        "--type", default="url", choices=["url", "domain", "email", "alias", "display", "country", "language"]
    )
    x.add_argument("--confirmed", action="store_true")
    x = sub.add_parser("decide")
    x.add_argument("id", type=int)
    x.add_argument("decision")
    x.add_argument("--relation", action="store_true")
    x = sub.add_parser("scan")
    x.add_argument("project", type=int)
    x.add_argument("--resume", type=int)
    x.add_argument("--config")
    for key in DEFAULTS:
        x.add_argument("--" + key.replace("_", "-"), type=int)
    x = sub.add_parser('bridges', help='Bounded loop for new aliases and domains from public evidence')
    x.add_argument('project', type=int)
    x.add_argument('root', type=int)
    x.add_argument('--queries', type=int, default=80)
    x.add_argument('--seconds', type=int, default=180)
    x.add_argument('--platforms', nargs='+')
    x.add_argument('--preview', action='store_true')
    x = sub.add_parser('diagnose', help='Why was a profile not found? No network')
    x.add_argument('project', type=int)
    x.add_argument('url')
    x = sub.add_parser('historical', help='Bounded public-archive read of one address')
    x.add_argument('project', type=int)
    x.add_argument('node', type=int)
    x.add_argument('--date', required=True)
    x.add_argument('--preview', action='store_true')
    x.add_argument('--read-content', action='store_true')
    x.add_argument('--consent', action='store_true')
    x = sub.add_parser('engine-check', help='One explicitly named account on a public instance')
    x.add_argument('engine')
    x.add_argument('host')
    x.add_argument('alias')
    x = sub.add_parser('import-definitions', help='Offline licensed definition normalization')
    x.add_argument('kind', choices=['Sherlock', 'Maigret', 'WhatsMyName'])
    x.add_argument('file')
    x.add_argument('--revision', required=True)
    x.add_argument('--license-file')
    x.add_argument('--output', required=True)
    x.add_argument('--limit', type=int, default=500)
    x = sub.add_parser('health', help='Explicit pair of public controls for a service; 24 h cache')
    x.add_argument('service')
    x.add_argument('--positive', required=True)
    x.add_argument('--negative', required=True)
    x = sub.add_parser('audit-health', help='Local health report and repair queue; no network')
    for flag in ('category', 'state', 'source', 'engine', 'tier'):
        x.add_argument('--' + flag)
    x.add_argument('--min-age', type=float)
    x.add_argument('--importance', type=int)
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--run', action='store_true', help='Run a bounded batch of explicit controls from a file')
    x.add_argument('--controls', help='Private JSON: service, positive, negative')
    x.add_argument('--max', type=int, default=5)
    x.add_argument('--stale-days', type=float)
    x = sub.add_parser('exposure-provider', help='HIBP metadata, no identifiers sent automatically')
    x.add_argument('operation', choices=['capabilities', 'catalog', 'subscription'])
    x = sub.add_parser('golden', help='Private local discovery benchmark; no network')
    x.add_argument('project', type=int)
    x.add_argument('file')
    x.add_argument('--search-id', type=int)
    x.add_argument('--save-snapshot', action='store_true')
    x = sub.add_parser('golden-history', help='Saved local benchmark measurements')
    x.add_argument('project', type=int)
    x.add_argument('--limit', type=int, default=20)
    x = sub.add_parser('golden-compare', help='Compare two immutable measurements')
    x.add_argument('project', type=int)
    x.add_argument('first', type=int)
    x.add_argument('second', type=int)
    x = sub.add_parser(
        'migrate-emails', help='Unify old email nodes into mailbox keys; without --apply only a plan'
    )
    x.add_argument('--apply', action='store_true')
    x.add_argument('--backup-dir')
    x = sub.add_parser('settings', help='Reading settings: robots.txt options and parallel services')
    x.add_argument('--set', nargs='*', default=[], metavar='KEY=VALUE')
    x.add_argument('--forget-robots', action='store_true')
    x = sub.add_parser('deadends', help='Unused leads connected to your accounts; no network')
    x.add_argument('project', type=int)
    x = sub.add_parser(
        'clusters', help='Suggested account groups from public evidence; no network, ownership unchanged'
    )
    x.add_argument('project', type=int)
    x.add_argument('--limit', type=int, default=20)
    x = sub.add_parser("show")
    x.add_argument("project", type=int)
    x = sub.add_parser("search", help="Stage 1: search for candidates in many sources")
    x.add_argument("project", type=int)
    x.add_argument("nickname")
    x.add_argument("--queries", type=int, default=40)
    x.add_argument("--seconds", type=int, default=120)
    x.add_argument('--github-only', action='store_true', help='Limit to the old single GitHub nick check')
    x.add_argument('--aliases', nargs='*', default=[])
    x.add_argument('--exact-only', action='store_true', help='Skip the extra search for similar names')
    x.add_argument('--candidates', type=int, default=50)
    x = sub.add_parser("check", help="Read selected candidates without changing ownership")
    x.add_argument("project", type=int)
    x.add_argument("ids", type=int, nargs="+")
    x = sub.add_parser('discover', help='Stage 1: search for candidates on many sites')
    x.add_argument('project', type=int)
    x.add_argument('nickname', nargs='?')
    x.add_argument('--platforms', nargs='+')
    x.add_argument('--resume', type=int)
    x.add_argument('--queries', type=int, default=40)
    x.add_argument('--seconds', type=int, default=120)
    x.add_argument('--aliases', nargs='*', default=[])
    x.add_argument('--exact-only', action='store_true')
    x.add_argument('--candidates', type=int, default=50)
    x = sub.add_parser('focus', help='Choose the point for further audit without confirming ownership')
    x.add_argument('project', type=int)
    x.add_argument('id', type=int, nargs='?')
    x = sub.add_parser('follow', help='Stage 2: read the focus point and accepted links')
    x.add_argument('project', type=int)
    x.add_argument('--depth', type=int, default=2)
    x.add_argument('--resume', type=int)
    x = sub.add_parser("export")
    x.add_argument("project", type=int)
    x.add_argument("--format", choices=["json", "markdown", 'html'], default="json")
    x.add_argument("--output", required=True)
    x.add_argument("--omit-email", action="store_true")
    x.add_argument("--exclude", type=int, nargs="*", default=[])
    x = sub.add_parser("posts")
    x.add_argument("source", type=int)
    x.add_argument("file")
    x = sub.add_parser("maigret")
    x.add_argument("project", type=int)
    x.add_argument("file")
    x = sub.add_parser("compare")
    x.add_argument("first", type=int)
    x.add_argument("second", type=int)
    x = sub.add_parser("delete")
    x.add_argument("project", type=int)
    x = sub.add_parser("serve")
    x.add_argument("--port", type=int, default=8765)
    sub.add_parser("demo")
    for command in ('search', 'discover'):
        parser = sub.choices[command]
        parser.add_argument(
            '--mode',
            choices=['QUICK', 'STANDARD', 'DEEP', 'CUSTOM', 'EXACT_ONLY', 'EXTENDED'],
            default='CUSTOM',
        )
        parser.add_argument(
            '--variants', action='store_true', help='Check bounded separator variants of the nick'
        )
        for field in ('first-name', 'last-name', 'location', 'keywords', 'birth-date'):
            parser.add_argument('--' + field, default='')
        parser.add_argument('--known-url', action='append', default=[])
    exposure_parser = sub.add_parser('exposure', help='Check your own email in HIBP; needs explicit consent')
    exposure_parser.add_argument('project', type=int)
    exposure_parser.add_argument('account')
    exposure_parser.add_argument(
        '--consent',
        action='store_true',
        help='Your own address (or authorised) and consent to send it to HIBP',
    )
    evaluation = sub.add_parser('benchmark', help='Ranking evaluation on fictional cases; no network')
    evaluation.add_argument('--cases', help='Optional JSON file with verified cases')
    a = p.parse_args()
    if a.cmd == 'benchmark':
        from .evaluation import benchmark

        try:
            if a.cases and Path(a.cases).stat().st_size > 5000000:
                raise ValueError('Dataset too large')
            cases = json.loads(Path(a.cases).read_text(encoding='utf-8')) if a.cases else None
            print(json.dumps(benchmark(cases), ensure_ascii=False, indent=2))
            return
        except (ValueError, OSError, KeyError, TypeError) as error:
            p.exit(2, 'Benchmark dataset error: ' + str(error) + '\n')
    if a.cmd == 'import-definitions':
        from .definition_import import convert

        try:
            if Path(a.file).stat().st_size > 15000000:
                raise ValueError('Dataset too large')
            license_text = Path(a.license_file).read_text(encoding='utf-8') if a.license_file else ''
            pack = convert(
                a.kind,
                json.loads(Path(a.file).read_text(encoding='utf-8')),
                a.revision,
                license_text,
                a.limit,
            )
            target = Path(a.output)
            if target.exists():
                raise ValueError('Output exists; choose a new path')
            target.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding='utf-8')
            print(
                json.dumps(
                    {
                        'definitions': len(pack['services']),
                        'rejected': len(pack['rejected']),
                        'license': pack['license'],
                        'live_validated': 0,
                    }
                )
            )
            return
        except (OSError, ValueError, TypeError, KeyError) as error:
            p.exit(2, str(error) + '\n')
    context = (
        (
            {k: getattr(a, k) for k in ('first_name', 'last_name', 'location', 'keywords', 'birth_date')}
            | {'known_urls': a.known_url}
        )
        if a.cmd in ('search', 'discover')
        else None
    )
    from .runtime import exclusive_runtime
    from contextlib import nullcontext

    needs_worker = (
        a.cmd
        in (
            'scan',
            'search',
            'check',
            'discover',
            'follow',
            'exposure',
            'delete',
            'bridges',
            'health',
            'engine-check',
            'historical',
        )
        or a.cmd == 'audit-health'
        and a.run
        or a.cmd == 'exposure-provider'
        and a.operation != 'capabilities'
        or a.cmd == 'migrate-emails'
        and a.apply
    )
    lease = exclusive_runtime(a.db) if needs_worker else nullcontext()
    try:
        lease.__enter__()
    except ValueError as error:
        p.exit(2, str(error) + '\n')
    try:
        store = Store(a.db)
    except Exception:
        lease.__exit__(None, None, None)
        raise
    try:
        if a.cmd == "create":
            result = store.project(a.name)
        elif a.cmd == "projects":
            result = store.rows("SELECT * FROM projects")
        elif a.cmd == "add":
            result = store.add(a.project, a.value, a.type, a.confirmed)
        elif a.cmd == "decide":
            store.decide(a.id, a.decision, a.relation)
            result = "Decision saved"
        elif a.cmd == "scan":
            options = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else {}
            if not isinstance(options, dict) or set(options) - set(DEFAULTS):
                raise ValueError("Unknown options")
            options.update({k: getattr(a, k) for k in DEFAULTS if getattr(a, k) is not None})
            result = scan(store, a.project, options, a.resume)
        elif a.cmd == 'bridges':
            from .bridgeflow import run, preview

            result = (
                preview(store, a.project, a.root)
                if a.preview
                else run(store, a.project, a.root, {'queries': a.queries, 'seconds': a.seconds}, a.platforms)
            )
        elif a.cmd == 'migrate-emails':
            from .emailmigration import plan as migration_plan, apply as migration_apply

            result = migration_apply(store, a.db, a.backup_dir) if a.apply else migration_plan(store)
        elif a.cmd == 'settings':
            from .settings import (
                save as save_settings,
                describe as describe_settings,
                DEFAULTS as setting_defaults,
            )

            changes = {}
            for item in a.set:
                if '=' not in item:
                    raise ValueError('Use KEY=VALUE')
                key, raw = item.split('=', 1)
                if key not in setting_defaults:
                    raise ValueError('Unknown setting: ' + key)
                changes[key] = (
                    (raw.lower() in ('1', 'true', 'tak', 'yes', 'on'))
                    if isinstance(setting_defaults[key], bool)
                    else raw if isinstance(setting_defaults[key], str) else int(raw)
                )
            if changes:
                save_settings(store, changes)
            if a.forget_robots:
                from .cooldowns import forget_robots

                forget_robots(store)
            result = describe_settings(store)
        elif a.cmd == 'deadends':
            from .deadends import report as dead_end_report

            result = dead_end_report(store, a.project)
        elif a.cmd == 'clusters':
            from .entitylinks import view as identity_view

            result = identity_view(store.snapshot(a.project), limit=a.limit)
        elif a.cmd == 'diagnose':
            from .diagnostics import explain

            result = explain(store, a.project, a.url)
        elif a.cmd == 'historical':
            from .archives import preview as archive_preview, lookup as archive_lookup

            result = (
                archive_preview(store, a.project, a.node, a.date)
                if a.preview
                else archive_lookup(store, a.project, a.node, a.date, a.read_content, a.consent)
            )
        elif a.cmd == 'engine-check':
            from .publicengines import lookup as engine_lookup
            from .network import Client

            result = engine_lookup(a.engine, a.host, a.alias, Client(queries=3, seconds=25, per_domain=3))
        elif a.cmd == 'health':
            from .health import validate as validate_health

            result = validate_health(store, a.service, a.positive, a.negative)
        elif a.cmd == 'audit-health':
            from .serviceaudit import report

            filters = {
                key: getattr(a, key)
                for key in ('category', 'state', 'source', 'engine', 'tier', 'min_age', 'importance')
                if getattr(a, key) is not None
            }
            if a.stale_days is not None:
                filters['min_age'] = a.stale_days
            if a.run:
                from .healthbatch import run

                if not a.controls:
                    raise ValueError('--run needs --controls with explicit control pairs')
                if Path(a.controls).stat().st_size > 100000:
                    raise ValueError('Control file too large')
                result = run(
                    store, json.loads(Path(a.controls).read_text(encoding='utf-8-sig')), filters, a.max
                )
            else:
                result = report(store, filters, a.limit)
        elif a.cmd == 'exposure-provider':
            from .exposureproviders import HIBP

            provider = HIBP(store)
            result = {
                'capabilities': provider.capabilities,
                'catalog': provider.list_incidents,
                'subscription': provider.health,
            }[a.operation]()
        elif a.cmd == 'golden':
            from .golden import evaluate as golden_evaluate, save_snapshot

            if Path(a.file).stat().st_size > 1000000:
                raise ValueError('Benchmark too large')
            result = (save_snapshot if a.save_snapshot else golden_evaluate)(
                store, a.project, json.loads(Path(a.file).read_text(encoding='utf-8')), search_id=a.search_id
            )
        elif a.cmd == 'golden-history':
            from .golden import snapshot_history

            result = snapshot_history(store, a.project, a.limit)
        elif a.cmd == 'golden-compare':
            from .golden import compare_snapshots

            result = compare_snapshots(store, a.project, a.first, a.second)
        elif a.cmd == "show":
            result = store.snapshot(a.project)
        elif a.cmd in ('search', 'discover') and a.mode != 'CUSTOM':
            from .scanmodes import policy
            from .pipeline import run as pipeline_run
            from .search import discover, results
            from .autoresume import search as resume_search, ROUND_CAP

            mode = policy(a.mode)
            if mode['branches']:
                id = pipeline_run(
                    store,
                    a.project,
                    a.nickname,
                    aliases=a.aliases,
                    criteria=context,
                    resume=getattr(a, 'resume', None),
                    scan_mode=a.mode,
                )
            else:
                id = discover(
                    store,
                    a.project,
                    a.nickname,
                    aliases=a.aliases,
                    criteria=context,
                    resume=getattr(a, 'resume', None),
                    scan_mode=a.mode,
                )
                if mode['auto_resume']:
                    resume_search(store, a.project, id, max_rounds=max(mode['continuations'], ROUND_CAP))
            result = next(r for r in results(store, a.project) if r['run']['id'] == id)
        elif a.cmd == "search":
            if a.github_only:
                from .discovery import prepare_nickname

                targets = prepare_nickname(store, a.project, a.nickname)
                result = {
                    "scan": scan(
                        store, a.project, {"queries": a.queries, "seconds": a.seconds}, targets=targets
                    ),
                    "scope": "GitHub; only the given nick; ownership unconfirmed",
                    "nodes": [store.node(i) for i in targets],
                }
            else:
                from .search import discover, results

                id = discover(
                    store,
                    a.project,
                    a.nickname,
                    options={'queries': a.queries, 'seconds': a.seconds, 'candidates': a.candidates},
                    aliases=a.aliases,
                    related=not a.exact_only,
                    criteria=context,
                    variants=a.variants,
                )
                result = next(r for r in results(store, a.project) if r['run']['id'] == id)
        elif a.cmd == "check":
            result = scan(store, a.project, targets=a.ids)
        elif a.cmd == 'discover':
            from .search import discover, results

            id = discover(
                store,
                a.project,
                a.nickname,
                a.platforms,
                {'queries': a.queries, 'seconds': a.seconds, 'candidates': a.candidates},
                resume=a.resume,
                aliases=a.aliases,
                related=not a.exact_only,
                criteria=context,
                variants=a.variants,
            )
            result = next(r for r in results(store, a.project) if r['run']['id'] == id)
        elif a.cmd == 'focus':
            store.set_focus(a.project, a.id)
            result = store.snapshot(a.project)['focus']
        elif a.cmd == 'follow':
            result = scan(store, a.project, {'depth': a.depth}, resume=a.resume, focused=True)
        elif a.cmd == 'exposure':
            from .exposure import check

            result = check(store, a.project, a.account, a.consent)
        elif a.cmd == "export":
            Path(a.output).write_text(
                export(
                    store,
                    a.project,
                    a.format,
                    a.omit_email,
                    a.exclude,
                    language=(
                        'pl' if os.environ.get('NICKTRAIL_LANG', 'en').lower().startswith('pl') else 'en'
                    ),
                ),
                encoding="utf-8",
            )
            result = a.output
        elif a.cmd in ("posts", "maigret"):
            path = Path(a.file)
            if path.stat().st_size > 5_000_000:
                raise ValueError("Import too large")
            data = json.loads(path.read_text(encoding="utf-8"))
            result = (
                imports.posts(store, a.source, data)
                if a.cmd == "posts"
                else imports.maigret(store, a.project, data)
            )
        elif a.cmd == "compare":
            result = store.compare(a.first, a.second)
        elif a.cmd == "delete":
            store.execute("DELETE FROM projects WHERE id=?", (a.project,))
            store.execute("VACUUM")
            result = "Project data deleted"
        elif a.cmd == "demo":
            from .demo import create

            result = create(store)
        elif a.cmd == "serve":
            from .web import serve

            store.db.close()
            serve(a.db, a.port)
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as e:
        # Messages from the core are Polish source strings; show them in the CLI language
        # (English by default, NICKTRAIL_LANG=pl for Polish).
        import os as _os
        from .localization import translate_message

        language = _os.environ.get('NICKTRAIL_LANG', 'en')
        p.exit(2, ("Błąd: " if language == 'pl' else "Error: ") + translate_message(str(e), language) + "\n")
    finally:
        store.db.close()
        lease.__exit__(None, None, None)


if __name__ == "__main__":
    main()
