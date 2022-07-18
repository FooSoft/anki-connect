import os

import aqt
import pytest

from conftest import ac, anki_connect_config_loaded, \
    set_up_test_deck_and_test_model_and_two_notes, \
    current_decks_and_models_etc_preserved, wait


# version is retrieved from config
def test_version(session_with_profile_loaded):
    with anki_connect_config_loaded(
        session=session_with_profile_loaded,
        web_bind_port=0,
    ):
        assert ac.version() == 6


def test_reloadCollection(setup):
    ac.reloadCollection()


def test_apiReflect(setup):
    result = ac.apiReflect(
        scopes=["actions", "invalidType"],
        actions=["apiReflect", "invalidMethod"]
    )
    assert result == {
        "scopes": ["actions"],
        "actions": ["apiReflect"]
    }


class TestProfiles:
    def test_getProfiles(self, session_with_profile_loaded):
        result = ac.getProfiles()
        assert result == ["test_user"]

    # waiting a little while gets rid of the cryptic warning:
    #   Qt warning: QXcbConnection: XCB error: 8 (BadMatch), sequence: 658,
    #   resource id: 2097216, major code: 42 (SetInputFocus), minor code: 0
    def test_loadProfile(self, session_with_profile_loaded):
        aqt.mw.unloadProfileAndShowProfileManager()
        wait(0.1)
        ac.loadProfile(name="test_user")


class TestExportImport:
    # since Anki 2.1.50, exporting media for some wild reason
    # will change the current working directory, which then gets removed.
    # see `exporting.py`, ctrl-f `os.chdir(self.mediaDir)`
    @pytest.fixture(autouse=True)
    def current_working_directory_preserved(self):
        cwd = os.getcwd()
        yield

        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(cwd)

    def test_exportPackage(self,  session_with_profile_loaded, setup):
        filename = session_with_profile_loaded.base + "/export.apkg"
        ac.exportPackage(deck="test_deck", path=filename)

    def test_importPackage(self, session_with_profile_loaded):
        filename = session_with_profile_loaded.base + "/export.apkg"

        with current_decks_and_models_etc_preserved():
            set_up_test_deck_and_test_model_and_two_notes()
            ac.exportPackage(deck="test_deck", path=filename)

        with current_decks_and_models_etc_preserved():
            assert "test_deck" not in ac.deckNames()
            ac.importPackage(path=filename)
            assert "test_deck" in ac.deckNames()


def test_interpret():
    fn_str = "def average_nums(*nums):\n    return sum(nums) / len(nums)"
    ac.interpret(fn_str)
    assert ac.interpret(
        "'average_nums' in globals() and callable(average_nums)") is True
    assert ac.interpret("average_nums(1, 2, 3)") == 2
    ac.interpret("del average_nums")
    return
