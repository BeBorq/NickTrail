"""Explicit nickname lookup, separate from ownership and graph expansion."""
import re
from .identity import identify


def prepare_nickname(store, project, nickname):
    if not isinstance(nickname, str): raise ValueError("Podaj nick GitHub")
    nickname = nickname.strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", nickname) or "--" in nickname:
        raise ValueError("Nick GitHub: 1–39 liter ASCII, cyfr lub pojedynczych łączników; bez łącznika na końcach")
    url = "https://github.com/" + nickname
    if identify(url)["kind"] != "profile": raise ValueError("To zastrzeżona ścieżka, nie nick profilu")
    if not store.rows("SELECT id FROM projects WHERE id=?", (project,)): raise ValueError("Nieznany projekt")
    store.add(project, nickname, "alias")
    return [store.add(project, url)]
