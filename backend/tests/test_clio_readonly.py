import httpx
import pytest

from app.clio_client import ClioReadClient, ClioWriteAttempt


def _transport(log):
    def handler(request: httpx.Request):
        log.append(request.method)
        if "page2" in str(request.url):
            return httpx.Response(200, json={"data": [{"id": 3}], "meta": {"paging": {}}})
        return httpx.Response(200, json={"data": [{"id": 1}, {"id": 2}],
                                         "meta": {"paging": {"next": "https://app.clio.com/api/v4/notes.json?page2=1"}}})
    return httpx.MockTransport(handler)


def test_only_get_is_exposed():
    c = ClioReadClient("tok", transport=_transport([]))
    for name in ("post", "put", "patch", "delete", "request"):
        assert not hasattr(c, name), f"ClioReadClient must not expose {name}()"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_send_refuses_writes(method):
    log = []
    c = ClioReadClient("tok", transport=_transport(log))
    with pytest.raises(ClioWriteAttempt):
        c._send(method, "https://app.clio.com/api/v4/notes.json")
    assert log == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_transport_hook_refuses_writes_even_bypassing_send(method):
    log = []
    c = ClioReadClient("tok", transport=_transport(log))
    with pytest.raises(ClioWriteAttempt):
        c._http.request(method, "https://app.clio.com/api/v4/notes.json")
    assert log == []


def test_get_all_follows_pagination():
    log = []
    c = ClioReadClient("tok", transport=_transport(log))
    assert [r["id"] for r in c.get_all("notes.json", {"matter_id": 1})] == [1, 2, 3]
    assert set(log) == {"GET"}
