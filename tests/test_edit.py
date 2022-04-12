from dataclasses import dataclass
from unittest.mock import MagicMock

import aqt.operations.note
import pytest

from conftest import get_dialog_instance, wait_until
from plugin.edit import Edit, DecentPreviewer, history, DOMAIN_PREFIX


NOTHING = object()


class Value:
    def __init__(self):
        self.value = NOTHING

    def set(self, value):
        self.value = value

    def has_been_set(self):
        return self.value is not NOTHING


@dataclass
class JavascriptDialogButtonManipulator:
    dialog: ...

    def eval_js(self, js):
        evaluation_result = Value()
        self.dialog.editor.web.evalWithCallback(js, evaluation_result.set)
        wait_until(evaluation_result.has_been_set)
        return evaluation_result.value

    def wait_until_toolbar_buttons_are_ready(self):
        ready_flag = Value()
        self.dialog.editor._links["set_ready_flag"] = ready_flag.set  # noqa
        self.dialog.run_javascript_after_toolbar_ready("pycmd('set_ready_flag');")
        wait_until(ready_flag.has_been_set)

    # preview button doesn't have an id, so find by label
    def click_preview_button(self):
        self.eval_js("""
            document.evaluate("//button[text()='Preview']", document)
                    .iterateNext()
                    .click()
        """)

    def click_button(self, button_id):
        self.eval_js(f"""
            document.getElementById("{DOMAIN_PREFIX}{button_id}").click()
        """)

    def is_button_disabled(self, button_id):
        return self.eval_js(f"""
            document.getElementById("{DOMAIN_PREFIX}{button_id}").disabled
        """)


##############################################################################


def test_edit_dialog_opens(setup):
    Edit.open_dialog_and_show_note_with_id(setup.note1_id)


def test_edit_dialog_opens_only_once(setup):
    dialog1 = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
    dialog2 = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
    assert dialog1 is dialog2


def test_edit_dialog_fails_to_open_with_invalid_note(setup):
    with pytest.raises(Exception):
        Edit.open_dialog_and_show_note_with_id(123)


class TestBrowser:
    @staticmethod
    def get_selected_card_ids():
        return get_dialog_instance("Browser").table.get_selected_card_ids()

    def test_dialog_opens(self, setup):
        dialog = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        dialog.show_browser()

    def test_selects_cards_of_last_note(self, setup):
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        Edit.open_dialog_and_show_note_with_id(setup.note2_id).show_browser()

        assert {*self.get_selected_card_ids()} == {*setup.note2_card_ids}

    def test_selects_cards_of_note_before_last_after_previous_button_pressed(self, setup):
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        dialog = Edit.open_dialog_and_show_note_with_id(setup.note2_id)

        def verify_that_the_table_shows_note2_cards_then_note1_cards():
            get_dialog_instance("Browser").table.select_all()
            assert {*self.get_selected_card_ids()[:2]} == {*setup.note2_card_ids}
            assert {*self.get_selected_card_ids()[2:]} == {*setup.note1_card_ids}

        dialog.show_previous()
        dialog.show_browser()
        assert {*self.get_selected_card_ids()} == {*setup.note1_card_ids}
        verify_that_the_table_shows_note2_cards_then_note1_cards()

        dialog.show_next()
        dialog.show_browser()
        assert {*self.get_selected_card_ids()} == {*setup.note2_card_ids}
        verify_that_the_table_shows_note2_cards_then_note1_cards()


class TestPreviewDialog:
    def test_opens(self, setup):
        edit_dialog = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        edit_dialog.show_preview()

    @pytest.fixture
    def dialog(self, setup):
        edit_dialog = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        preview_dialog: DecentPreviewer = edit_dialog.show_preview()

        def press_next_button(times=0):
            for _ in range(times):
                preview_dialog._last_render = 0         # render without delay
                preview_dialog._on_next()

        preview_dialog.press_next_button = press_next_button

        yield preview_dialog

    @pytest.mark.parametrize(
        "next_button_presses, current_card, "
        "showing_question_only, previous_enabled, next_enabled",
        [
            pytest.param(0, 0, True, False, True,
                    id="next button pressed 0 times; first card, question"),
            pytest.param(1, 0, False, True, True,
                    id="next button pressed 1 time;  first card, answer"),
            pytest.param(2, 1, True,  True, True,
                    id="next button pressed 2 times; second card, question"),
            pytest.param(3, 1, False, True, False,
                    id="next button pressed 3 times; second card, answer"),
            pytest.param(4, 1, False, True, False,
                    id="next button pressed 4 times; second card still, answer"),
        ]
    )
    def test_navigation(self, dialog, next_button_presses, current_card,
            showing_question_only, previous_enabled, next_enabled):
        dialog.press_next_button(times=next_button_presses)
        assert dialog.adapter.current == current_card
        assert dialog.showing_question_and_can_show_answer() is showing_question_only
        assert dialog._should_enable_prev() is previous_enabled
        assert dialog._should_enable_next() is next_enabled


class TestButtons:
    @pytest.fixture
    def manipulator(self, setup):
        dialog = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        return JavascriptDialogButtonManipulator(dialog)

    def test_preview_button_can_be_clicked(self, manipulator, monkeypatch):
        monkeypatch.setattr(manipulator.dialog, "show_preview", MagicMock())
        manipulator.wait_until_toolbar_buttons_are_ready()
        manipulator.click_preview_button()
        wait_until(lambda: manipulator.dialog.show_preview.call_count == 1)

    def test_addon_buttons_can_be_clicked(self, manipulator):
        manipulator.wait_until_toolbar_buttons_are_ready()
        manipulator.click_button(button_id="browse")
        wait_until(lambda: get_dialog_instance("Browser") is not None)

    def test_addon_buttons_get_disabled_enabled(self, setup, manipulator):
        Edit.open_dialog_and_show_note_with_id(setup.note2_id)
        manipulator.wait_until_toolbar_buttons_are_ready()
        assert manipulator.is_button_disabled("previous") is False
        assert manipulator.is_button_disabled("next") is True


class TestHistory:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        history.note_ids = []

    def test_single_note(self, setup):
        assert history.note_ids == []
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        assert history.note_ids == [setup.note1_id]

    def test_two_notes(self, setup):
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        Edit.open_dialog_and_show_note_with_id(setup.note2_id)
        assert history.note_ids == [setup.note1_id, setup.note2_id]

    def test_old_note_reopened(self, setup):
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        Edit.open_dialog_and_show_note_with_id(setup.note2_id)
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        assert history.note_ids == [setup.note2_id, setup.note1_id]

    def test_navigation(self, setup):
        dialog = Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        Edit.open_dialog_and_show_note_with_id(setup.note2_id)

        dialog.show_previous()
        assert dialog.note.id == setup.note1_id

        dialog.show_previous()
        assert dialog.note.id == setup.note1_id

        dialog.show_next()
        assert dialog.note.id == setup.note2_id

        dialog.show_next()
        assert dialog.note.id == setup.note2_id


class TestNoteDeletionElsewhere:
    @pytest.fixture
    def delete_note(self, run_background_tasks_on_main_thread):
        """
        Yields a function that accepts a single note id and deletes the note,
        running the required hooks in sync
        """
        return (
            lambda note_id: aqt.operations.note
                .remove_notes(parent=None, note_ids=[note_id])  # noqa
                .run_in_background()
        )

    @staticmethod
    def edit_dialog_is_open():
        return aqt.dialogs._dialogs[Edit.dialog_registry_tag][1] is not None  # noqa

    @pytest.fixture
    def dialog(self, setup):
        Edit.open_dialog_and_show_note_with_id(setup.note1_id)
        yield Edit.open_dialog_and_show_note_with_id(setup.note2_id)

    def test_one_of_the_history_notes_is_deleted_and_dialog_stays(self,
            setup, dialog, delete_note):
        assert dialog.note.id == setup.note2_id

        delete_note(setup.note2_id)
        assert self.edit_dialog_is_open()
        assert dialog.note.id == setup.note1_id

    def test_all_of_the_history_notes_are_deleted_and_dialog_closes(self,
            setup, dialog, delete_note):
        delete_note(setup.note1_id)
        delete_note(setup.note2_id)
        assert not self.edit_dialog_is_open()
