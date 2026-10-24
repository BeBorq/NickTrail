"""Deterministic e-mail canonicalization and public hashing for identity bridging.

Rationale
---------
NickTrail already treats a shared public e-mail as the strongest identity
signal (`graphsignals`, kind ``shared_public_email``).  The weak point is that
two accounts only bridge when the *exact same string* was extracted on both
sides.  In practice the same person publishes the address in different forms:

    Jan.Kowalski@GMail.com   johnkowalski+github@gmail.com   jan.kowalski@googlemail.com

All three are the same Gmail mailbox, yet the previous ``email_key`` (lowercase
the domain only) produced three different nodes and therefore no bridge.  This
module adds a *canonical* key that merges provider-equivalent forms, while
keeping the *exact* observed address so the panel can still show precisely what
was published on each profile.

It is additive and side-effect free: existing ``identity.email_key`` keeps its
old meaning (used as a durable node key); canonicalization is a second,
clearly-labelled key used only for linking.  Nothing here contacts the network,
reads breach data, or decides ownership.
"""
from __future__ import annotations
import hashlib
import re

# Providers that are case-insensitive in the local part *and* ignore dots, and
# treat "+tag" as sub-addressing of the same mailbox.  Kept deliberately small
# and evidence-based; unknown providers get only the safe transforms below.
_GMAIL = {"gmail.com", "googlemail.com"}

# Providers documented to support "+tag" sub-addressing (tag is stripped for the
# merge key only).  Conservative allow-list — never guess for unknown hosts.
_PLUS_TAG = _GMAIL | {
    "outlook.com", "hotmail.com", "live.com", "fastmail.com",
    "proton.me", "protonmail.com", "pm.me", "icloud.com", "me.com", "mac.com",
    "yahoo.com",  # Yahoo uses "-" disposable addresses, not "+"; handled below
}

# A few providers alias their domains to one canonical mailbox domain.
_DOMAIN_ALIASES = {
    "googlemail.com": "gmail.com",
    "ymail.com": "yahoo.com",
    "rocketmail.com": "yahoo.com",
    "pm.me": "proton.me",
    "protonmail.com": "proton.me",
    "hotmail.com": "outlook.com",
    "live.com": "outlook.com",
    "me.com": "icloud.com",
    "mac.com": "icloud.com",
}

_LOCAL_OK = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+")


def _split(address: str):
    address = address.strip()
    # One '@' only; reject anything that is not a plausible single address.
    if address.count("@") != 1:
        raise ValueError("Nieprawidłowy adres e-mail")
    local, domain = address.rsplit("@", 1)
    domain = domain.strip().strip(".").lower()
    if not local or not domain or "." not in domain or " " in address:
        raise ValueError("Nieprawidłowy adres e-mail")
    try:
        domain = domain.encode("idna").decode().lower()
    except (UnicodeError, ValueError):
        raise ValueError("Nieprawidłowa domena e-mail")
    return local, domain


def exact_key(address: str) -> str:
    """Stable key preserving the local part (case-insensitive domain only).

    This matches the historical `identity.email_key` behaviour and is what the
    durable node identity should keep using, so existing rows do not move.
    """
    local, domain = _split(address)
    return local + "@" + domain


def canonical_key(address: str):
    """Return (canonical, meta) where equal canonicals mean 'same mailbox'.

    `meta` explains every transform applied, so a reviewer can see *why* two
    different-looking addresses were merged — important because this key drives
    account linking.  Raises ValueError for anything that is not one address.
    """
    local, domain = _split(address)
    applied = []

    domain_mapped = _DOMAIN_ALIASES.get(domain, domain)
    if domain_mapped != domain:
        applied.append(f"domena {domain}->{domain_mapped}")
    domain = domain_mapped

    # Local part: lower-casing is safe for linking (the vast majority of
    # providers deliver case-insensitively); we record it as an assumption.
    low = local.lower()
    if low != local:
        applied.append("lokalna część: wielkość liter pominięta")
    local = low

    # Sub-addressing "+tag" (and Yahoo's "-tag") removed for the merge key.
    if domain in _PLUS_TAG and "+" in local:
        local = local.split("+", 1)[0]
        applied.append('odcięto "+tag"')
    elif domain == "yahoo.com" and "-" in local:
        local = local.split("-", 1)[0]
        applied.append('odcięto "-tag" (Yahoo)')

    # Dot-insensitivity for Gmail-class mailboxes only.
    if domain in {"gmail.com"} and "." in local:
        local = local.replace(".", "")
        applied.append("usunięto kropki (Gmail)")

    if not local:
        raise ValueError("Pusta lokalna część po normalizacji")
    canonical = local + "@" + domain
    return canonical, {
        "canonical": canonical,
        "exact": exact_key(address),
        "domain": domain,
        "transforms": applied,
        # True only when canonical == exact: no assumptions were needed, so the
        # merge is exact rather than provider-heuristic.
        "lossless": not applied,
    }


def email_hashes(address: str) -> dict:
    """Public avatar-service hashes of an address (Gravatar/Libravatar style).

    Gravatar hashes the trimmed, lower-cased address with MD5; newer services
    use SHA-256 of the same normalized form.  Computing both lets the graph
    bridge a profile that only exposes an avatar *hash* to a profile that
    exposes the matching raw address — without ever sending the address.
    """
    local, domain = _split(address)
    norm = (local.lower() + "@" + domain).encode("utf-8")
    return {
        "md5": hashlib.md5(norm).hexdigest(),
        "sha256": hashlib.sha256(norm).hexdigest(),
    }


# md5 is 32 hex chars, sha256 is 64.  Used to recognise a hash-shaped token.
_HEX = re.compile(r"\A[0-9a-f]{32}\Z|\A[0-9a-f]{64}\Z")


def gravatar_hash_from_url(url: str):
    """Extract the hash from a gravatar.com / libravatar avatar URL, else None."""
    m = re.search(r"(?:gravatar\.com|libravatar\.org)/avatar/([0-9a-fA-F]{32,64})", url)
    if not m:
        return None
    h = m.group(1).lower()
    return h if _HEX.match(h) else None
