"""robots.txt handling for the crawler (FR-AUD-01), per RFC 9309: a missing file (4xx) allows
everything, and an unavailable one (5xx or network failure) is treated as disallow-all."""
from urllib.robotparser import RobotFileParser

from app.audit.fetcher import USER_AGENT, FetchResult

AGENT = USER_AGENT.split("/")[0]


class Robots:
    def __init__(self, result: FetchResult) -> None:
        self.present = result.status == 200 and result.body is not None
        self.error = result.error  # set when the host could not be reached at all
        self._allow_all = False
        self._deny_all = False
        self._parser = RobotFileParser()
        if self.present:
            self._parser.parse((result.body or "").splitlines())
        elif result.status is not None and 400 <= result.status < 500:
            self._allow_all = True
        else:
            self._deny_all = True

    @property
    def unavailable(self) -> bool:
        return self._deny_all

    def allows(self, url: str) -> bool:
        if self._allow_all:
            return True
        if self._deny_all:
            return False
        return self._parser.can_fetch(AGENT, url)

    @property
    def sitemaps(self) -> list[str]:
        return list(self._parser.site_maps() or []) if self.present else []
