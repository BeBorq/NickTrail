import json
import time
import hashlib
import http.client
from . import adapters
from .identity import team_email
from .network import Client, Limit
from .storage import now
from .readstatus import note as note_read

DEFAULTS = {"depth": 2, "profiles": 50, "pages": 20, "queries": 40, "seconds": 120, "per_domain": 15}


def record(store, node, items, complete=False):
    if complete:
        store.execute(
            "UPDATE evidence SET current=0 WHERE source=? AND location NOT IN ('imported_post','imported_profile')",
            (node['id'],),
        )
        store.execute(
            "UPDATE evidence SET assessment='clue' WHERE (source=? OR target=?) AND assessment='reciprocal'",
            (node['id'], node['id']),
        )
    for item in items:
        if 'discord' in item:
            target = store.add(
                node['project'], item['discord'], 'discord', seed=False, depth=node['depth'] + 1
            )
            relation = 'mentions'
        elif "email" in item:
            target = store.add(node["project"], item["email"], "email", seed=False, depth=node["depth"] + 1)
            relation = "team_contact" if team_email(item["email"]) else item["relation"]
        else:
            target = store.add(node["project"], item["url"], seed=False, depth=node["depth"] + 1)
            relation = item["relation"]
        store.evidence(
            node["project"],
            node["id"],
            target,
            relation,
            item.get("source_url", node["url"]),
            item["location"],
            item["snippet"],
            item.get("method", "parser"),
            author=item.get("author", ""),
            date=item.get("date", ""),
            context=item.get("context", "own"),
        )


VALID_STATES = ("found", "not_found", "blocked", "error", "partial", "unsupported", "unverified")
FOLLOWED_RELATIONS = "('links','claims_ownership')"
SKIPPED_NOTE = (
    "Pominięto: wymaga zatwierdzenia własności, adresu obsługiwanego źródła lub mieści się poza głębokością"
)
FOCUS_NOTE = (
    "Odczyt punktu odniesienia; rozwijane są wyłącznie aktualne zatwierdzone odnośniki. "
    "Własność pozostaje bez zmian."
)
CHECK_NOTE = (
    "Sprawdzenie wskazanych kandydatów. Własność pozostaje bez zmian; "
    "brak automatycznego rozwijania linków."
)


class ScanState:
    """Everything a scan keeps between steps; saved in the `scans` row so it can resume."""

    def __init__(self, project, opts, rendered, targets, focus_root, distances):
        self.project = project
        self.opts = opts
        self.rendered = rendered
        self.targets = targets
        self.explicit = targets is not None
        self.focus_root = focus_root
        self.distances = distances
        self.queue, self.visited, self.notes = [], [], []
        self.scan_id = None
        self.prior = 0

    @property
    def focused(self):
        return self.focus_root is not None

    def saved_options(self):
        saved = dict(self.opts)
        if self.explicit:
            saved["_targets"] = self.targets
        if self.rendered:
            saved["_rendered"] = True
        if self.focused:
            saved.update(_focus_root=self.focus_root, _distances=self.distances)
        return saved


def _check_options(options):
    opts = DEFAULTS | (options or {})
    if (
        set(opts) != set(DEFAULTS)
        or any(type(v) is not int or v < 0 for v in opts.values())
        or opts["seconds"] == 0
    ):
        raise ValueError("Nieprawidłowe limity")
    return opts


def _check_targets(store, project, targets):
    if (
        not isinstance(targets, list)
        or not targets
        or len(targets) > 100
        or any(type(i) is not int for i in targets)
    ):
        raise ValueError("Wybierz od 1 do 100 elementów")
    for id in targets:
        if store.node(id)["project"] != project:
            raise ValueError("Element z innego projektu")


def _resume(store, project, resume):
    row = store.rows("SELECT * FROM scans WHERE id=? AND project=?", (resume, project))
    if not row or row[0]["status"] not in ("paused", "limited", "running", "failed"):
        raise ValueError("Nie można wznowić")
    row = row[0]
    opts = json.loads(row["options"])
    state = ScanState(
        project,
        opts,
        rendered=opts.pop("_rendered", False),
        targets=opts.pop("_targets", None),
        focus_root=opts.pop("_focus_root", None),
        distances=opts.pop("_distances", {}),
    )
    state.queue, state.visited, state.notes = (
        json.loads(row["queue"]),
        json.loads(row["visited"]),
        json.loads(row["notes"]),
    )
    state.scan_id, state.prior = resume, row["requests"]
    return state


def _start(store, state):
    nodes = store.snapshot(state.project)["nodes"]
    state.queue = [
        n["id"]
        for n in nodes
        if (n["id"] in state.targets if state.explicit else n["ownership"] == "mine")
        and n["ownership"] != "not_mine"
        and n["kind"] in ("profile", "page")
        and (state.explicit or n["depth"] <= state.opts["depth"])
    ]
    state.notes = [
        {"node": n["id"], "reason": SKIPPED_NOTE}
        for n in nodes
        if n["id"] not in state.queue and (not state.explicit or n["id"] in state.targets)
    ]
    if state.explicit:
        state.notes.append({"reason": FOCUS_NOTE if state.focused else CHECK_NOTE})
    state.scan_id = store.execute(
        "INSERT INTO scans(project,started,status,queue,options) VALUES(?,?,?,?,?)",
        (state.project, now(), "running", json.dumps(state.queue), json.dumps(state.saved_options())),
    ).lastrowid


def _reachable_from_visited(store, state, id):
    """In a focused scan a node is read only through an accepted link from an already read account."""
    paths = store.rows(
        "SELECT source FROM evidence WHERE target=? AND decision='accepted' AND current=1 "
        "AND relation IN " + FOLLOWED_RELATIONS,
        (id,),
    )
    return any(
        e["source"] in state.visited
        and store.node(e["source"])["ownership"] != "not_mine"
        and store.node(e["source"])["state"] == "found"
        for e in paths
    )


def _skip(state, node, distance):
    return (
        node["id"] in state.visited
        or node["ownership"] == "not_mine"
        or (not state.explicit and node["ownership"] != "mine")
        or (distance > state.opts["depth"] and (not state.explicit or state.focused))
    )


def _over_limit(store, state, node):
    pages = sum(store.node(i)["platform"] == "Strona" for i in state.visited)
    if node["platform"] == "Strona":
        return pages >= state.opts["pages"]
    return len(state.visited) - pages >= state.opts["profiles"]


def _read(store, state, node, client):
    """Read one node; Limit propagates, any other failure becomes an error result."""
    try:
        if state.rendered:
            from .rendered import read as read_rendered

            return read_rendered(node, client)
        return adapters.read(node, client)
    except Limit:
        raise
    except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
        return {"state": "error", "detail": type(e).__name__}
    except Exception as e:
        # An unexpected response from one site must not end the whole scan.
        from .errorlog import write as log_error

        log_error(store, "scan #" + str(state.scan_id) + " " + str(node.get("url")), e)
        return {
            "state": "error",
            "detail": "Błąd programu przy odczycie ("
            + type(e).__name__
            + "); pominięto. Szczegóły w pliku .errors.log obok bazy.",
        }


def _checked(result, node):
    """Reject malformed adapter results and an account ID that changed under the same address."""
    if not isinstance(result, dict) or result.get("state") not in VALID_STATES:
        return {"state": "error", "detail": "Nieprawidłowy wynik adaptera"}
    observed = result.get("data") or {}
    previous = json.loads(node["data"])
    if (
        result["state"] == "found"
        and previous.get("stable_id")
        and observed.get("stable_id")
        and previous["stable_id"] != observed["stable_id"]
    ):
        return {
            "state": "error",
            "detail": "Zmienił się trwały identyfikator konta pod tym adresem; wymagana ręczna weryfikacja",
            # Keep what was observed, so the conflicting ID stays visible in the scan history.
            "data": observed,
        }
    return result


def _observe(store, state, id, result):
    observed = dict(result.get("data") or {})
    if result["state"] == "found":
        observed["evidence_digest"] = hashlib.sha256(
            json.dumps(result.get("evidence", []), sort_keys=True).encode()
        ).hexdigest()
    store.execute(
        "INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?)",
        (
            state.scan_id,
            id,
            result["state"],
            json.dumps(observed, ensure_ascii=False, sort_keys=True),
            result.get("detail", ""),
        ),
    )
    note_read(store, id, result["state"], result.get("detail", ""))
    return observed


def _apply_found(store, state, node, result, observed):
    """Save a found profile and its evidence. Returns False when the profile could not be applied."""
    id = node["id"]
    try:
        store.apply_profile(
            state.project,
            result.get("canonical_url", node["url"]),
            observed,
            node_id=id,
            seed=bool(node["seed"]),
            depth=node["depth"],
            partial=state.rendered or result.get("data_complete") is False,
        )
    except ValueError as error:
        store.execute("UPDATE nodes SET state='error' WHERE id=?", (id,))
        store.execute(
            "UPDATE observations SET state='error',detail=? WHERE scan=? AND node=?",
            (str(error), state.scan_id, id),
        )
        note_read(store, id, "error", str(error))
        state.notes.append({"node": id, "reason": str(error)})
        return False
    record(store, store.node(id), result.get("evidence", []), complete=not state.rendered)
    return True


def _expand_focus(store, state, id, distance):
    """Queue accepted links of a read account, one level further from the focus root."""
    edges = store.rows(
        "SELECT target FROM evidence WHERE source=? AND decision='accepted' AND current=1 "
        "AND relation IN " + FOLLOWED_RELATIONS,
        (id,),
    )
    for edge in edges:
        target = store.node(edge["target"])
        if (
            target["kind"] in ("profile", "page")
            and target["ownership"] != "not_mine"
            and target["id"] not in state.visited
            and target["id"] not in state.queue
        ):
            state.queue.append(target["id"])
            state.distances[str(target["id"])] = distance + 1


def _checkpoint(store, state, client):
    if state.focused:
        store.execute(
            "UPDATE scans SET options=? WHERE id=?", (json.dumps(state.saved_options()), state.scan_id)
        )
    store.execute(
        "UPDATE scans SET queue=?,visited=?,requests=? WHERE id=?",
        (json.dumps(state.queue), json.dumps(state.visited), state.prior + client.count, state.scan_id),
    )


def scan(
    store,
    project,
    options=None,
    resume=None,
    client=None,
    stopped=lambda: False,
    targets=None,
    focused=False,
    rendered=False,
):
    """Read confirmed (or explicitly chosen) accounts and record the public evidence they publish.

    Ownership is never changed here. A focused scan starts from the selected account and follows
    only accepted, current links, at most `depth` steps away.
    """
    opts = _check_options(options)
    if not store.rows("SELECT id FROM projects WHERE id=?", (project,)):
        raise ValueError("Nieznany projekt")
    focus_root, distances = None, {}
    if focused and not resume:
        selection = store.rows("SELECT node FROM focus WHERE project=?", (project,))
        if not selection:
            raise ValueError("Wybierz profil, od którego zacząć")
        focus_root = selection[0]["node"]
        targets = [focus_root]
        distances[str(focus_root)] = 0
    if targets is not None:
        _check_targets(store, project, targets)
    if resume:
        state = _resume(store, project, resume)
    else:
        state = ScanState(project, opts, rendered, targets, focus_root, distances)
        _start(store, state)
    opts = state.opts
    client = client or Client(
        queries=max(0, opts["queries"] - state.prior),
        seconds=opts["seconds"],
        per_domain=opts["per_domain"],
        browser_resources=state.rendered,
    )
    from .cooldowns import bind as bind_cooldowns

    bind_cooldowns(client, store)
    status = "completed"
    queue = state.queue
    try:
        while queue:
            if stopped():
                status = "paused"
                break
            id = queue[0]
            node = store.node(id)
            distance = state.distances.get(str(id), node["depth"])
            if state.focused and id != state.focus_root and not _reachable_from_visited(store, state, id):
                queue.pop(0)
                continue
            if _skip(state, node, distance):
                queue.pop(0)
                continue
            if _over_limit(store, state, node):
                state.notes.append({"node": id, "reason": "Limit stron lub profili"})
                status = "limited"
                break
            try:
                result = _read(store, state, node, client)
            except Limit:
                status = "limited"
                break
            result = _checked(result, node)
            observed = _observe(store, state, id, result)
            if result["state"] == "found":
                if not _apply_found(store, state, node, result, observed):
                    state.visited.append(id)
                    queue.pop(0)
                    continue
                if state.focused and distance < opts["depth"]:
                    _expand_focus(store, state, id, distance)
            else:
                store.execute("UPDATE nodes SET state=? WHERE id=?", (result["state"], id))
                state.notes.append({"node": id, "reason": result.get("detail", result["state"])})
            state.visited.append(id)
            queue.pop(0)
            _checkpoint(store, state, client)
    except KeyboardInterrupt:
        status = "paused"
    except Exception as error:
        status = "failed"
        state.notes.append({"reason": "Nieoczekiwany błąd: " + type(error).__name__})
        raise
    finally:
        store.execute(
            "UPDATE scans SET status=?,finished=?,queue=?,visited=?,requests=?,notes=? WHERE id=?",
            (
                status,
                now(),
                json.dumps(queue),
                json.dumps(state.visited),
                state.prior + client.count,
                json.dumps(state.notes, ensure_ascii=False),
                state.scan_id,
            ),
        )
    return state.scan_id
