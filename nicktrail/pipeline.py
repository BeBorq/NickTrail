"""Durable exact -> enrich -> branches -> weak discovery orchestration."""

import json
from .stages import phase


def run(
    store,
    project,
    nickname=None,
    platforms=None,
    options=None,
    aliases=(),
    related=False,
    criteria=None,
    resume=None,
    branch_options=None,
    auto_resume=True,
    stopped=lambda: False,
    pause=lambda: False,
    variants=False,
    scan_mode='CUSTOM',
):
    from .scanmodes import policy

    if resume:
        saved = store.rows('SELECT options FROM searches WHERE id=? AND project=?', (resume, project))
        if saved:
            scan_mode = json.loads(saved[0]['options']).get('_scan_mode', 'CUSTOM')
    mode = policy(scan_mode)
    rounds = mode['continuations']
    if scan_mode != 'CUSTOM':
        branch_options = mode['branch_options']
        auto_resume = mode['auto_resume']
    from .search import discover
    from .autoresume import search as finish_search, branches as finish_branches, ROUND_CAP
    from .branches import explore

    if scan_mode != 'CUSTOM' and not mode['branches']:
        id = discover(
            store,
            project,
            nickname,
            platforms,
            options,
            aliases=aliases,
            related=related,
            criteria=criteria,
            resume=resume,
            stopped=stopped,
            variants=variants,
            scan_mode=scan_mode,
        )
        if auto_resume:
            finish_search(store, project, id, stopped, pause, max_rounds=max(rounds, ROUND_CAP))
        return id
    id = discover(
        store,
        project,
        nickname,
        platforms,
        options,
        aliases=aliases,
        related=related,
        criteria=criteria,
        resume=resume,
        stopped=stopped,
        stop_after_exact=True,
        variants=variants,
        scan_mode=scan_mode,
    )
    if auto_resume:
        finish_search(
            store, project, id, stopped, pause, max_rounds=max(rounds, ROUND_CAP), stop_after_exact=True
        )
    pending = store.rows("SELECT platform,mode FROM search_tasks WHERE search=? AND state='pending'", (id,))
    if stopped() or any(phase(t['platform'], t['mode']) in ('A_EXACT', 'B_ENRICH') for t in pending):
        return id
    store.execute("UPDATE searches SET status='stage_ready' WHERE id=?", (id,))

    def settings():
        return json.loads(store.rows('SELECT options FROM searches WHERE id=?', (id,))[0]['options'])

    opts = settings()
    plan = opts.get('_pipeline')

    def save():
        opts = settings()
        opts['_pipeline'] = plan
        store.execute('UPDATE searches SET options=? WHERE id=?', (json.dumps(opts), id))

    if plan is None:
        tasks = store.rows('SELECT platform,mode,nodes FROM search_tasks WHERE search=?', (id,))
        ids = list(
            dict.fromkeys(
                n
                for t in tasks
                if phase(t['platform'], t['mode']) in ('A_EXACT', 'B_ENRICH')
                for n in json.loads(t['nodes'])
            )
        )
        roots = []
        from .accountentities import non_person

        focused = {r['node'] for r in store.rows('SELECT node FROM focus WHERE project=?', (project,))}
        for n in ids:
            node = store.node(n)
            data = json.loads(node['data'])
            if non_person(node) and node['ownership'] != 'mine' and n not in focused:
                continue
            if (
                node['state'] == 'found'
                and node['ownership'] != 'not_mine'
                and node['kind'] in ('profile', 'page')
                and not data.get('indexed_only')
                and not data.get('definition_only')
            ):
                roots.append(n)
        # Only new plans are ordered; saved branch origins/offsets remain durable.
        from .frontier import bridge_bonus

        roots.sort(key=lambda n: -bridge_bonus(store.node(n)['url']))
        plan = {'roots': roots, 'offset': 0, 'runs': [], 'current': None}
        save()
    while plan['offset'] < len(plan['roots']) and not stopped():
        if plan['current']:
            branch = plan['current']
            state = store.rows('SELECT status FROM branch_runs WHERE id=?', (branch,))[0]['status']
            if state in ('paused', 'limited', 'failed'):
                explore(store, project, resume=branch, options=branch_options, stopped=stopped)
        else:
            branch = explore(
                store,
                project,
                plan['roots'][plan['offset'] : plan['offset'] + 200],
                branch_options,
                stopped=stopped,
                origin_key='search:' + str(id) + ':batch:' + str(plan['offset']),
            )
            plan['current'] = branch
            plan['runs'].append(branch)
            save()
        if auto_resume:
            finish_branches(
                store, project, branch, branch_options, stopped, pause, max_rounds=max(rounds, ROUND_CAP)
            )
        state = store.rows('SELECT status FROM branch_runs WHERE id=?', (branch,))[0]['status']
        if state != 'completed':
            return id
        plan['offset'] = min(len(plan['roots']), plan['offset'] + 200)
        plan['current'] = None
        save()
    if stopped():
        return id
    state = store.rows('SELECT status FROM searches WHERE id=?', (id,))[0]['status']
    if state == 'stage_ready':
        discover(store, project, resume=id, stopped=stopped)
        if auto_resume:
            finish_search(store, project, id, stopped, pause, max_rounds=max(rounds, ROUND_CAP))
    return id
