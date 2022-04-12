import concurrent.futures
import time
from contextlib import contextmanager
from dataclasses import dataclass

import aqt.operations.note
import pytest
import anki.collection
from _pytest.monkeypatch import MonkeyPatch  # noqa
from pytest_anki._launch import anki_running, temporary_user  # noqa
from waitress import wasyncore

from plugin import AnkiConnect
from plugin.edit import Edit
from plugin.util import DEFAULT_CONFIG

try:
    from PyQt6 import QtTest
except ImportError:
    from PyQt5 import QtTest


ac = AnkiConnect()


# wait for n seconds, while events are being processed
def wait(seconds):
    milliseconds = int(seconds * 1000)
    QtTest.QTest.qWait(milliseconds)  # noqa


def wait_until(booleanish_function, at_most_seconds=30):
    deadline = time.time() + at_most_seconds

    while time.time() < deadline:
        if booleanish_function():
            return
        wait(0.01)

    raise Exception(f"Function {booleanish_function} never once returned "
                    f"a positive value in {at_most_seconds} seconds")


def delete_model(model_name):
    model = ac.collection().models.byName(model_name)
    ac.collection().models.remove(model["id"])


def close_all_dialogs_and_wait_for_them_to_run_closing_callbacks():
    aqt.dialogs.closeAll(onsuccess=lambda: None)
    wait_until(aqt.dialogs.allClosed)


def get_dialog_instance(name):
    return aqt.dialogs._dialogs[name][1]    # noqa


# waitress is a WSGI server that Anki starts to serve css etc to its web views.
# it seems to have a race condition issue;
# the main loop thread is trying to `select.select` the sockets
# which a worker thread is closing because of a dead connection.
# this is especially pronounced in tests,
# as we open and close windows rapidly--and so web views and their connections.
# this small patch makes waitress skip actually closing the sockets
# (unless the server is shutting down--if it is, loop exceptions are ignored).
# while the unclosed sockets might accumulate,
# this should not pose an issue in test environment.
# see https://github.com/Pylons/waitress/issues/374
@contextmanager
def waitress_patched_to_prevent_it_from_dying():
    original_close = wasyncore.dispatcher.close
    sockets_that_must_not_be_garbage_collected = []     # lists are thread-safe

    def close(self):
        if not aqt.mw.mediaServer.is_shutdown:
            sockets_that_must_not_be_garbage_collected.append(self.socket)
            self.socket = None
        original_close(self)

    with MonkeyPatch().context() as monkey:
        monkey.setattr(wasyncore.dispatcher, "close", close)
        yield


@contextmanager
def anki_patched_to_prevent_backups():
    with MonkeyPatch().context() as monkey:
        if ac._anki21_version < 50:
            monkey.setitem(aqt.profiles.profileConf, "numBackups", 0)
        else:
            monkey.setattr(anki.collection.Collection, "create_backup",
                           lambda *args, **kwargs: True)
        yield


@contextmanager
def empty_anki_session_started():
    with waitress_patched_to_prevent_it_from_dying():
        with anki_patched_to_prevent_backups():
            with anki_running(
                qtbot=None,  # noqa
                enable_web_debugging=False,
                profile_name="test_user",
            ) as session:
                yield session


@contextmanager
def profile_created_and_loaded(session):
    with temporary_user(session.base, "test_user", "en_US"):
        with session.profile_loaded():
            yield session


@contextmanager
def anki_connect_config_loaded(session, web_bind_port):
    with session.addon_config_created(
        package_name="plugin",
        default_config=DEFAULT_CONFIG,
        user_config={**DEFAULT_CONFIG, "webBindPort": web_bind_port}
    ):
        yield


@contextmanager
def current_decks_and_models_etc_preserved():
    deck_names_before = ac.deckNames()
    model_names_before = ac.modelNames()

    try:
        yield
    finally:
        deck_names_after = ac.deckNames()
        model_names_after = ac.modelNames()

        deck_names_to_delete = {*deck_names_after} - {*deck_names_before}
        model_names_to_delete = {*model_names_after} - {*model_names_before}

        ac.deleteDecks(decks=deck_names_to_delete, cardsToo=True)
        for model_name in model_names_to_delete:
            delete_model(model_name)

        ac.guiDeckBrowser()


@dataclass
class Setup:
    deck_id: int
    note1_id: int
    note2_id: int
    note1_card_ids: "list[int]"
    note2_card_ids: "list[int]"
    card_ids: "list[int]"


def set_up_test_deck_and_test_model_and_two_notes():
    ac.createModel(
        modelName="test_model",
        inOrderFields=["field1", "field2"],
        cardTemplates=[
            {"Front": "{{field1}}", "Back": "{{field2}}"},
            {"Front": "{{field2}}", "Back": "{{field1}}"}
        ],
        css="* {}",
    )

    deck_id = ac.createDeck("test_deck")

    note1_id = ac.addNote(dict(
        deckName="test_deck",
        modelName="test_model",
        fields={"field1": "note1 field1", "field2": "note1 field2"},
        tags={"tag1"},
    ))

    note2_id = ac.addNote(dict(
        deckName="test_deck",
        modelName="test_model",
        fields={"field1": "note2 field1", "field2": "note2 field2"},
        tags={"tag2"},
    ))

    note1_card_ids = ac.findCards(query=f"nid:{note1_id}")
    note2_card_ids = ac.findCards(query=f"nid:{note2_id}")
    card_ids = ac.findCards(query="deck:test_deck")

    return Setup(
        deck_id=deck_id,
        note1_id=note1_id,
        note2_id=note2_id,
        note1_card_ids=note1_card_ids,
        note2_card_ids=note2_card_ids,
        card_ids=card_ids,
    )


#############################################################################


def pytest_addoption(parser):
    parser.addoption("--tear-down-profile-after-each-test",
                     action="store_true",
                     default=True)
    parser.addoption("--no-tear-down-profile-after-each-test", "-T",
                     action="store_false",
                     dest="tear_down_profile_after_each_test")


def pytest_report_header(config):
    if config.option.forked:
        return "test isolation: perfect; each test is run in a separate process"
    if config.option.tear_down_profile_after_each_test:
        return "test isolation: good; user profile is torn down after each test"
    else:
        return "test isolation: poor; only newly created decks and models " \
               "are cleaned up between tests"


@pytest.fixture(autouse=True)
def run_background_tasks_on_main_thread(request, monkeypatch):  # noqa
    """
    Makes background operations such as card deletion execute on main thread
    and execute the callback immediately
    """
    def run_in_background(task, on_done=None, kwargs=None):
        future = concurrent.futures.Future()

        try:
            future.set_result(task(**kwargs if kwargs is not None else {}))
        except BaseException as e:
            future.set_exception(e)

        if on_done is not None:
            on_done(future)

    monkeypatch.setattr(aqt.mw.taskman, "run_in_background", run_in_background)


# don't use run_background_tasks_on_main_thread for tests that don't run Anki
def pytest_generate_tests(metafunc):
    if (
        run_background_tasks_on_main_thread.__name__ in metafunc.fixturenames
        and session_scope_empty_session.__name__ not in metafunc.fixturenames
    ):
        metafunc.fixturenames.remove(run_background_tasks_on_main_thread.__name__)


@pytest.fixture(scope="session")
def session_scope_empty_session():
    with empty_anki_session_started() as session:
        yield session


@pytest.fixture(scope="session")
def session_scope_session_with_profile_loaded(session_scope_empty_session):
    with profile_created_and_loaded(session_scope_empty_session):
        yield session_scope_empty_session


@pytest.fixture
def session_with_profile_loaded(session_scope_empty_session, request):
    """
    Like anki_session fixture from pytest-anki, but:
      * Default profile is loaded
      * It's relying on session-wide app instance so that
        it can be used without forking every test;
        this can be useful to speed up tests and also
        to examine Anki's stdout/stderr, which is not visible with forking.
      * If command line option --no-tear-down-profile-after-each-test is passed,
        only the newly created decks and models are deleted.
        Otherwise, the profile is completely torn down after each test.
        Tearing down the profile is significantly slower.
    """
    if request.config.option.tear_down_profile_after_each_test:
        with profile_created_and_loaded(session_scope_empty_session):
            yield session_scope_empty_session
    else:
        session = request.getfixturevalue(
            session_scope_session_with_profile_loaded.__name__
        )
        with current_decks_and_models_etc_preserved():
            yield session


@pytest.fixture
def setup(session_with_profile_loaded):
    """
    Like session_with_profile_loaded, but also:
      * Added are:
        * A deck `test_deck`
        * A model `test_model` with fields `filed1` and `field2`
          and two cards per note
        * Two notes with two valid cards each using the above deck and model
      * Edit dialog is registered with dialog manager
      * Any dialogs, if open, are safely closed on exit
    """
    Edit.register_with_anki()
    yield set_up_test_deck_and_test_model_and_two_notes()
    close_all_dialogs_and_wait_for_them_to_run_closing_callbacks()
