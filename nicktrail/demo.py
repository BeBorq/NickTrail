from .storage import Store
from .engine import scan


class FixtureClient:
    """Explicitly fictional transport; never selected by a network scan."""

    count = 0

    def get(self, url):
        self.count += 1
        if url in (
            "https://api.github.com/users/fictional-nicktrail",
            'https://api.github.com/user/900000001',
        ):
            return {
                "state": "found",
                "text": '{"id":900000001,"login":"fictional-nicktrail","name":"Fictional Person","blog":"https://nicktrail.example/about","bio":"I recommend https://github.com/another-fictional/demo"}',
            }
        if url == "https://nicktrail.example/about":
            return {
                "state": "found",
                "text": '<p>My GitHub is https://github.com/fictional-nicktrail</p><p>Contact: support@nicktrail.example</p>',
                "url": url,
            }
        return {"state": "not_found", "detail": "No fictional response"}


def create(store):
    project = store.project("DEMO — fictional data only")
    store.add(project, "https://github.com/fictional-nicktrail", confirmed=True)
    store.add(project, "https://nicktrail.example/about", confirmed=True)
    scan(store, project, client=FixtureClient())
    return project
