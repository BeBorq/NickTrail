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
        store.execute("UPDATE evidence SET current=0 WHERE source=? AND location NOT IN ('imported_post','imported_profile')",(node['id'],))
        store.execute("UPDATE evidence SET assessment='clue' WHERE (source=? OR target=?) AND assessment='reciprocal'",(node['id'],node['id']))
    for item in items:
        if 'discord' in item:
            target=store.add(node['project'],item['discord'],'discord',seed=False,depth=node['depth']+1);relation='mentions'
        elif "email" in item:
            target = store.add(node["project"], item["email"], "email", seed=False, depth=node["depth"] + 1)
            relation = "team_contact" if team_email(item["email"]) else item["relation"]
        else:
            target = store.add(node["project"], item["url"], seed=False, depth=node["depth"] + 1)
            relation = item["relation"]
        store.evidence(node["project"], node["id"], target, relation, item.get("source_url", node["url"]), item["location"], item["snippet"], item.get("method", "parser"), author=item.get("author", ""), date=item.get("date", ""), context=item.get("context", "own"))


def scan(store, project, options=None, resume=None, client=None, stopped=lambda: False, targets=None, focused=False, rendered=False):
    opts = DEFAULTS | (options or {})
    if set(opts) != set(DEFAULTS) or any(type(v) is not int or v < 0 for v in opts.values()) or opts["seconds"] == 0:
        raise ValueError("Nieprawidłowe limity")
    if not store.rows("SELECT id FROM projects WHERE id=?", (project,)):
        raise ValueError("Nieznany projekt")
    explicit = targets is not None
    focus_root = None
    distances = {}
    if focused and not resume:
        selection = store.rows('SELECT node FROM focus WHERE project=?', (project,))
        if not selection: raise ValueError('Wybierz profil, od którego zacząć')
        focus_root = selection[0]['node']
        targets, explicit = [focus_root], True
        distances[str(focus_root)] = 0
    if explicit:
        if not isinstance(targets, list) or not targets or len(targets) > 100 or any(type(i) is not int for i in targets):
            raise ValueError("Wybierz od 1 do 100 elementów")
        for id in targets:
            if store.node(id)["project"] != project: raise ValueError("Element z innego projektu")
    if resume:
        row = store.rows("SELECT * FROM scans WHERE id=? AND project=?", (resume, project))
        if not row or row[0]["status"] not in ("paused", "limited", "running",'failed'): raise ValueError("Nie można wznowić")
        row = row[0]
        opts = json.loads(row["options"])
        rendered=opts.pop('_rendered',False)
        saved_targets = opts.pop("_targets", None)
        focus_root = opts.pop('_focus_root', None)
        distances = opts.pop('_distances', {})
        explicit = saved_targets is not None
        targets = saved_targets
        queue, visited, notes = json.loads(row["queue"]), json.loads(row["visited"]), json.loads(row["notes"])
        scan_id, prior = resume, row["requests"]
    else:
        queue = [n["id"] for n in store.snapshot(project)["nodes"] if
                 (n["id"] in targets if explicit else n["ownership"] == "mine") and
                 n["ownership"] != "not_mine" and n["kind"] in ("profile", "page") and (explicit or n["depth"] <= opts["depth"])]
        visited, notes, prior = [], [], 0
        notes = [{"node": n["id"], "reason": "Pominięto: wymaga zatwierdzenia własności, adresu obsługiwanego źródła lub mieści się poza głębokością"}
                 for n in store.snapshot(project)["nodes"] if n["id"] not in queue and (not explicit or n['id'] in targets)]
        if explicit: notes.append({"reason": "Odczyt punktu odniesienia; rozwijane są wyłącznie aktualne zatwierdzone odnośniki. Własność pozostaje bez zmian." if focus_root is not None else "Sprawdzenie wskazanych kandydatów. Własność pozostaje bez zmian; brak automatycznego rozwijania linków."})
        saved_options = opts | ({"_targets": targets} if explicit else {})
        if rendered:saved_options['_rendered']=True
        if focus_root is not None: saved_options.update(_focus_root=focus_root, _distances=distances)
        scan_id = store.execute("INSERT INTO scans(project,started,status,queue,options) VALUES(?,?,?,?,?)", (project, now(), "running", json.dumps(queue), json.dumps(saved_options))).lastrowid
    client = client or Client(queries=max(0, opts["queries"] - prior), seconds=opts["seconds"], per_domain=opts["per_domain"],browser_resources=rendered)
    from .cooldowns import bind as bind_cooldowns
    bind_cooldowns(client,store)
    status = "completed"
    try:
        while queue:
            if stopped(): status = "paused"; break
            id = queue[0]
            node = store.node(id)
            distance = distances.get(str(id), node['depth'])
            if focus_root is not None and id != focus_root:
                paths = store.rows("SELECT source FROM evidence WHERE target=? AND decision='accepted' AND current=1 AND relation IN ('links','claims_ownership')", (id,))
                if not any(e['source'] in visited and store.node(e['source'])['ownership']!='not_mine' and store.node(e['source'])['state']=='found' for e in paths):
                    queue.pop(0); continue
            if id in visited or node["ownership"] == "not_mine" or (not explicit and node["ownership"] != "mine") or (distance > opts["depth"] and (not explicit or focus_root is not None)):
                queue.pop(0); continue
            pages = sum(store.node(i)["platform"] == "Strona" for i in visited)
            if (node["platform"] == "Strona" and pages >= opts["pages"]) or (node["platform"] != "Strona" and len(visited) - pages >= opts["profiles"]):
                notes.append({"node": id, "reason": "Limit stron lub profili"}); status = "limited"; break
            try:
                if rendered:
                    from .rendered import read as read_rendered
                    result=read_rendered(node,client)
                else:result = adapters.read(node, client)
            except Limit:
                status = "limited"; break
            except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
                result = {"state": "error", "detail": type(e).__name__}
            except Exception as e:
                # An unexpected response from one site must not end the whole scan.
                from .errorlog import write as log_error
                log_error(store, 'scan #' + str(scan_id) + ' ' + str(node.get('url')), e)
                result = {"state": "error", "detail": "Błąd programu przy odczycie (" + type(e).__name__ + "); pominięto. Szczegóły w pliku .errors.log obok bazy."}
            if not isinstance(result, dict) or result.get("state") not in ("found", "not_found", "blocked", "error", "partial", "unsupported", "unverified"):
                result = {"state": "error", "detail": "Nieprawidłowy wynik adaptera"}
            observed = dict(result.get("data") or {})
            previous=json.loads(node['data'])
            if result['state']=='found' and previous.get('stable_id') and observed.get('stable_id') and previous['stable_id']!=observed['stable_id']:
                result={'state':'error','detail':'Zmienił się trwały identyfikator konta pod tym adresem; wymagana ręczna weryfikacja'}
            if result["state"] == "found":
                observed["evidence_digest"] = hashlib.sha256(json.dumps(result.get("evidence", []), sort_keys=True).encode()).hexdigest()
            data = json.dumps(observed, ensure_ascii=False, sort_keys=True)
            store.execute("INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?)", (scan_id, id, result["state"], data, result.get("detail", "")))
            note_read(store, id, result["state"], result.get("detail", ""))
            if result["state"] == "found":
                try:
                    store.apply_profile(project,result.get('canonical_url',node['url']),observed,node_id=id,seed=bool(node['seed']),depth=node['depth'],partial=rendered or result.get('data_complete') is False)
                except ValueError as error:
                    store.execute("UPDATE nodes SET state='error' WHERE id=?",(id,))
                    store.execute("UPDATE observations SET state='error',detail=? WHERE scan=? AND node=?",(str(error),scan_id,id))
                    note_read(store, id, 'error', str(error))
                    notes.append({'node':id,'reason':str(error)})
                    visited.append(id);queue.pop(0);continue
                node=store.node(id)
                record(store, node, result.get("evidence", []),complete=not rendered)
                if focus_root is not None and distance < opts['depth']:
                    edges = store.rows("SELECT target FROM evidence WHERE source=? AND decision='accepted' AND current=1 AND relation IN ('links','claims_ownership')", (id,))
                    for edge in edges:
                        target = store.node(edge['target'])
                        if target['kind'] in ('profile','page') and target['ownership'] != 'not_mine' and target['id'] not in visited and target['id'] not in queue:
                            queue.append(target['id'])
                            distances[str(target['id'])] = distance + 1
            else:
                store.execute("UPDATE nodes SET state=? WHERE id=?", (result["state"], id))
                notes.append({"node": id, "reason": result.get("detail", result["state"])})
            visited.append(id); queue.pop(0)
            if focus_root is not None:
                saved = opts | {'_targets': targets, '_focus_root': focus_root, '_distances': distances}
                store.execute('UPDATE scans SET options=? WHERE id=?', (json.dumps(saved), scan_id))
            store.execute("UPDATE scans SET queue=?,visited=?,requests=? WHERE id=?", (json.dumps(queue), json.dumps(visited), prior + client.count, scan_id))
    except KeyboardInterrupt: status = "paused"
    except Exception as error:
        status='failed';notes.append({'reason':'Nieoczekiwany błąd: '+type(error).__name__})
        raise
    finally:
        store.execute("UPDATE scans SET status=?,finished=?,queue=?,visited=?,requests=?,notes=? WHERE id=?", (status, now(), json.dumps(queue), json.dumps(visited), prior + client.count, json.dumps(notes, ensure_ascii=False), scan_id))
    return scan_id
