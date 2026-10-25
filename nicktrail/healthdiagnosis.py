"""Evidence-limited maintenance diagnoses; hypotheses are never account absence."""


def diagnose(health, telemetry, revision):
    reason = str(health.get('reason', '')).upper()
    controls = telemetry.get('controls', [])
    if revision == 'CHANGED' and health.get('positive_passed') and health.get('negative_passed'):
        return {
            'code': 'DETECTOR_REVISION_CHANGED',
            'summary': 'Kod lub definicja zmieniły się po kontroli; ponowna para dopiero po wygaśnięciu cache.',
        }
    if 'INVALID' in reason and 'CONTROL' in reason:
        return {
            'code': 'INVALID_CONTROL',
            'summary': 'Popraw regułę konta kontrolnego; ta próba nie ocenia sprawności źródła.',
        }
    if any(400 in c.get('http_statuses', []) for c in controls) and not (
        health.get('positive_passed') and health.get('negative_passed')
    ):
        return {
            'code': 'API_ERROR_SEMANTICS_UNRESOLVED',
            'summary': 'API odrzuciło zapytanie HTTP 400. Sprawdź format/semantykę błędu; to nie awaria sieci ani dowód braku konta.',
        }
    for needle, code, summary in (
        (
            'DNS_ERROR',
            'DNS_LOOKUP_FAILED',
            'Nie udało się rozwiązać wskazanej domeny; nie zastępuj jej podobną nazwą ani nie zakładaj usunięcia wszystkich kont.',
        ),
        (
            'ROBOTS_RESTRICTED',
            'ROBOTS_RESTRICTION',
            'Automatyczny odczyt zabroniony lub wymaga wolniejszego tempa; kontrola ręczna.',
        ),
        (
            'RATE_LIMITED',
            'PROVIDER_RATE_LIMIT',
            'Poczekaj na koniec przerwy dostawcy; nie zmieniaj adresu w celu obejścia limitu.',
        ),
        ('LOGIN_REQUIRED', 'LOGIN_REQUIRED', 'Brak anonimowego dostępu; nie omijaj logowania.'),
        (
            'JS_REQUIRED',
            'JS_REQUIRED',
            'Brak odczytu statycznego; ewentualny jawny odczyt przeglądarką musi przestrzegać polityki źródła.',
        ),
        (
            'REDIRECT',
            'CANONICAL_OR_REDIRECT_MISMATCH',
            'Sprawdź kanoniczny adres, zmianę ścieżki i zakres instancji.',
        ),
        (
            'PROFILE_ALIAS_MISMATCH',
            'ALIAS_OR_CASE_MISMATCH',
            'Sprawdź normalizację nazwy oraz publiczną historię zmiany nicku.',
        ),
        (
            'UNVERIFIED_LEAD',
            'PROFILE_MARKUP_INCONCLUSIVE',
            'Nie potwierdzono metadanych profilu; możliwa zmiana HTML/JSON, JavaScript albo przestarzała definicja.',
        ),
        ('USERNAME_RULE', 'USERNAME_RULE_CHANGED', 'Porównaj regułę nicku z dokumentacją źródła.'),
    ):
        if needle in reason:
            return {'code': code, 'summary': summary}
    if health.get('positive_state') == 'not_found':
        return {
            'code': 'POSITIVE_CONTROL_OR_ROUTE_STALE',
            'summary': 'Znany profil nie został potwierdzony; sprawdź najpierw kontrolę, URL i aktualność importu.',
        }
    return {
        'code': 'NO_LIVE_PAIR' if not health.get('checked_at') else 'NO_SPECIFIC_FAILURE_ESTABLISHED',
        'summary': (
            'Brak zapisanej pary na żywo.'
            if not health.get('checked_at')
            else 'Nie ustalono dodatkowej przyczyny; nie zgaduj usunięcia witryny ani własności profilu.'
        ),
    }
