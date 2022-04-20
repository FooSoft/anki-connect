import json
import multiprocessing
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial

import pytest
from pytest_anki._launch import anki_running  # noqa
from pytest_anki._util import find_free_port  # noqa

from plugin import AnkiConnect
from tests.conftest import wait_until, \
        empty_anki_session_started, \
        anki_connect_config_loaded, \
        profile_created_and_loaded


@contextmanager
def function_running_in_a_process(context, function):
    process = context.Process(target=function)
    process.start()

    try:
        yield process
    finally:
        process.join()


# todo stop the server?
@contextmanager
def anki_connect_web_server_started():
    plugin = AnkiConnect()
    plugin.startWebServer()
    yield plugin


@dataclass
class Client:
    port: int

    @staticmethod
    def make_request(action, **params):
        return {"action": action, "params": params, "version": 6}

    def send_request(self, action, **params):
        request_data = self.make_request(action, **params)
        json_bytes = json.dumps(request_data).encode("utf-8")
        return json.loads(self.send_bytes(json_bytes))

    def send_bytes(self, bytes, headers={}):  # noqa
        request_url = f"http://localhost:{self.port}"
        request = urllib.request.Request(request_url, bytes, headers)
        response = urllib.request.urlopen(request).read()
        return response

    def wait_for_web_server_to_come_live(self, at_most_seconds=30):
        deadline = time.time() + at_most_seconds

        while time.time() < deadline:
            try:
                self.send_request("version")
                return
            except urllib.error.URLError:
                time.sleep(0.01)

        raise Exception(f"Anki-Connect web server did not come live "
                        f"in {at_most_seconds} seconds")


# spawning requires a top-level function for pickling
def external_anki_entry_function(web_bind_port, exit_event):
    with empty_anki_session_started() as session:
        with anki_connect_config_loaded(session, web_bind_port):
            with anki_connect_web_server_started():
                with profile_created_and_loaded(session):
                    wait_until(exit_event.is_set)


@contextmanager
def external_anki_running(process_run_method):
    context = multiprocessing.get_context(process_run_method)
    exit_event = context.Event()
    web_bind_port = find_free_port()
    function = partial(external_anki_entry_function, web_bind_port, exit_event)

    with function_running_in_a_process(context, function) as process:
        client = Client(port=web_bind_port)
        client.wait_for_web_server_to_come_live()

        try:
            yield client
        finally:
            exit_event.set()

    assert process.exitcode == 0


# if a Qt app was already launched in current process,
# launching a new Qt app, even from grounds up, fails or hangs.
# of course, this includes forked processes. therefore,
#   * if launching without --forked, use the `spawn` process run method;
#   * otherwise, use the `fork` method, as it is significantly faster.
#     with --forked, each test has its fixtures assembled inside the fork,
#     which means that when the test begins, Qt was never started in the fork.
@pytest.fixture(scope="module")
def external_anki(request):
    """
    Runs Anki in an external process, with the plugin loaded and started.
    On exit, neatly ends the process and makes sure its exit code is 0.
    Yields a client that can send web request to the external process.
    """
    with external_anki_running(
        "fork" if request.config.option.forked else "spawn"
    ) as client:
        yield client


##############################################################################


def test_successful_request(external_anki):
    response = external_anki.send_request("version")
    assert response == {"error": None, "result": 6}


def test_can_handle_multiple_requests(external_anki):
    assert external_anki.send_request("version") == {"error": None, "result": 6}
    assert external_anki.send_request("version") == {"error": None, "result": 6}


def test_multi_request(external_anki):
    version_request = Client.make_request("version")
    response = external_anki.send_request("multi", actions=[version_request] * 3)
    assert response == {
        "error": None,
        "result": [{"error": None, "result": 6}] * 3
    }


def test_request_with_empty_body_returns_version_banner(external_anki):
    response = external_anki.send_bytes(b"")
    assert response == b"AnkiConnect v.6"


def test_failing_request_due_to_bad_arguments(external_anki):
    response = external_anki.send_request("addNote", bad="request")
    assert response["result"] is None
    assert "unexpected keyword argument" in response["error"]


def test_failing_request_due_to_anki_raising_exception(external_anki):
    response = external_anki.send_request("suspend", cards=[-123])
    assert response["result"] is None
    assert "Card was not found" in response["error"]


def test_failing_request_due_to_bad_encoding(external_anki):
    response = json.loads(external_anki.send_bytes(b"\xe7\x8c"))
    assert response["result"] is None
    assert "can't decode" in response["error"]


def test_failing_request_due_to_bad_json(external_anki):
    response = json.loads(external_anki.send_bytes(b'{1: 2}'))
    assert response["result"] is None
    assert "in double quotes" in response["error"]


def test_403_in_case_of_disallowed_origin(external_anki):
    with pytest.raises(urllib.error.HTTPError, match="403"):  # good request/json
        json_bytes = json.dumps(Client.make_request("version")).encode("utf-8")
        external_anki.send_bytes(json_bytes, headers={b"origin": b"foo"})

    with pytest.raises(urllib.error.HTTPError, match="403"):  # bad json
        external_anki.send_bytes(b'{1: 2}', headers={b"origin": b"foo"})
