"""Explicit archive capabilities. Never switch providers to evade restrictions."""


class WaybackProvider:
    id = 'InternetArchive'

    def preview(self, store, project, node, date):
        from .archives import preview

        return preview(store, project, node, date)

    def lookup(self, store, project, node, date, **options):
        from .archives import lookup

        return lookup(store, project, node, date, **options)


def capabilities(store):
    from .cooldowns import active

    return [
        {
            'provider': 'InternetArchive',
            'state': (
                'RATE_LIMITED'
                if any(r['host'] in ('archive.org', 'web.archive.org') for r in active(store))
                else 'CONFIGURED_NOT_LIVE_VALIDATED'
            ),
            'api': 'https://archive.org/help/wayback_api.php',
            'implemented': True,
            'scope': 'one explicit URL/date, metadata first, separate content consent',
            'cache_seconds': 86400,
            'automatic_failover': False,
        },
        {
            'provider': 'Arquivo.pt',
            'state': 'RESEARCH_ONLY',
            'api': 'https://github.com/arquivo/pwa-technologies/wiki/APIs',
            'implemented': False,
            'reason': 'Provider terms and intended-use scope need individual review; no automatic substitute for Wayback',
        },
        {
            'provider': 'CommonCrawl',
            'state': 'UNSUITABLE_FOR_AUTOMATIC_IDENTITY_HARVESTING',
            'api': 'https://commoncrawl.org/terms-of-use',
            'implemented': False,
            'reason': 'Terms restrict harvesting personal information separately from crawled content; no bulk/index/WARC ingestion',
        },
    ]
