import json
import threading
import urllib.error
import urllib.request

import pytest

from memlikehuman.models import Scope
from memlikehuman.web import WebServer


@pytest.fixture
def server(tmp_path):
    server = WebServer(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(server, path, data=None, token=True, headers=None):
    headers = headers or {}
    if token:
        headers["X-MemLikeHuman-Token"] = server.token
    req = urllib.request.Request(server.origin + path, data=data, headers=headers)
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5)


def test_loopback_auth_origin_host_and_static_assets(server):
    assert server.server_address[0] == "127.0.0.1"
    for path in ("/", "/style.css", "/app.js"):
        with request(server, path, token=False) as response:
            assert response.status == 200
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    for headers in ({}, {"Origin": "https://evil.example"}, {"Host": "evil.example"}):
        with pytest.raises(urllib.error.HTTPError) as error:
            request(server, "/api/overview", token=bool(headers), headers=headers)
        assert error.value.code == 403
    assert json.load(request(server, "/api/overview"))["libraries"][0]["id"] == "main"


def test_http_edit_export_import_and_failure(server):
    event = {
        "action": "event",
        "payload": {
            "event_id": "test",
            "text": "<script>alert('x')</script>",
            "role": "user",
            "source": "synthetic",
        },
    }
    assert json.load(request(server, "/api/edit", json.dumps(event).encode()))["event_id"] == "test"
    exported = request(server, "/api/export?format=jsonl").read()
    imported = json.load(request(server, "/api/import?name=Test", exported))
    assert server.dashboard.browse(imported["library"], Scope(), "events")["total"] == 1
    with pytest.raises(urllib.error.HTTPError) as error:
        request(server, "/api/edit", b'{"action":"event","payload":{"text":"private-secret"}}')
    assert b"private-secret" not in error.value.read()
    with pytest.raises(urllib.error.HTTPError):
        request(server, "/api/export?library=..%2F..%2Fother")
    assert server.dashboard.browse("main", Scope(), "events")["total"] == 1
