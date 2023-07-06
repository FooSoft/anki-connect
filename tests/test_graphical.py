import pytest

from conftest import ac, anki_version, wait_until, \
        close_all_dialogs_and_wait_for_them_to_run_closing_callbacks, \
        get_dialog_instance


def test_guiBrowse(setup):
    ac.guiBrowse()


def test_guiDeckBrowser(setup):
    ac.guiDeckBrowser()


# todo executing this test without running background tasks on main thread
#   rarely causes media server (`aqt.mediasrv`) to fail:
#   its `run` method raises OSError: invalid file descriptor.
#   this can cause other tests to fail to tear down;
#   particularly, any dialogs with editor may fail to close
#   due to their trying to save the note first, which is done via web view,
#   which fails to complete due to corrupt media server. investigate?
def test_guiCheckDatabase(setup, run_background_tasks_on_main_thread):
    ac.guiCheckDatabase()


def test_guiDeckOverview(setup):
    assert ac.guiDeckOverview(name="test_deck") is True


def test_guiImportFile(setup):
    if anki_version >= (2, 1, 52):
        ac.guiImportFile()


class TestAddCards:
    note = {
        "deckName": "test_deck",
        "modelName": "Basic",
        "fields": {"Front": "new front1", "Back": "new back1"},
        "tags": ["tag1"]
    }

    # an actual small image, you can see it if you run the test with GUI
    # noinspection SpellCheckingInspection
    base64_gif = "R0lGODlhBQAEAHAAACwAAAAABQAEAIH///8AAAAAAAAAAAACB0QMqZcXDwoAOw=="

    picture = {
        "picture": [
            {
                "data": base64_gif,
                "filename": "smiley.gif",
                "fields": ["Front"],
            }
        ]
    }

    @staticmethod
    def click_on_add_card_dialog_save_button():
        dialog = get_dialog_instance("AddCards")
        dialog.addButton.click()

    # todo previously, these tests were verifying
    #   that the return value of `guiAddCards` is `int`.
    #   while it is indeed `int`, on modern Anki it is also always a `0`,
    #   so we consider it useless. update documentation?
    def test_without_note(self, setup):
        ac.guiAddCards()

    def test_with_note(self, setup):
        ac.guiAddCards(note=self.note)
        self.click_on_add_card_dialog_save_button()
        close_all_dialogs_and_wait_for_them_to_run_closing_callbacks()

        assert len(ac.findCards(query="new")) == 1

    def test_with_note_and_a_picture(self, setup):
        ac.guiAddCards(note={**self.note, **self.picture})
        self.click_on_add_card_dialog_save_button()
        close_all_dialogs_and_wait_for_them_to_run_closing_callbacks()

        assert len(ac.findCards(query="new")) == 1
        assert ac.retrieveMediaFile(filename="smiley.gif") == self.base64_gif


class TestReviewActions:
    @pytest.fixture
    def reviewing_started(self, setup):
        assert ac.guiDeckReview(name="test_deck") is True

    def test_startCardTimer(self, reviewing_started):
        assert ac.guiStartCardTimer() is True

    def test_guiShowQuestion(self, reviewing_started):
        assert ac.guiShowQuestion() is True
        assert ac.reviewer().state == "question"

    def test_guiShowAnswer(self, reviewing_started):
        assert ac.guiShowAnswer() is True
        assert ac.reviewer().state == "answer"

    def test_guiAnswerCard(self, reviewing_started):
        ac.guiShowAnswer()
        reviews_before = ac.cardReviews(deck="test_deck", startID=0)
        assert ac.guiAnswerCard(ease=4) is True

        reviews_after = ac.cardReviews(deck="test_deck", startID=0)
        assert len(reviews_after) == len(reviews_before) + 1

    def test_guiUndo(self, reviewing_started):
        ac.guiShowAnswer()
        reviews_before = ac.cardReviews(deck="test_deck", startID=0)
        assert ac.guiAnswerCard(ease=4) is True

        reviews_after_answer = ac.cardReviews(deck="test_deck", startID=0)
        assert len(reviews_after_answer) == len(reviews_before) + 1

        assert ac.guiUndo() is True

        reviews_after_undo = ac.cardReviews(deck="test_deck", startID=0)
        assert len(reviews_after_undo) == len(reviews_before)


class TestSelectedNotes:
    def test_with_valid_deck_query(self, setup):
        ac.guiBrowse(query="deck:test_deck")
        wait_until(ac.guiSelectedNotes)
        assert ac.guiSelectedNotes()[0] in {setup.note1_id, setup.note2_id}


    def test_with_invalid_deck_query(self, setup):
        ac.guiBrowse(query="deck:test_deck")
        wait_until(ac.guiSelectedNotes)

        ac.guiBrowse(query="deck:invalid")
        wait_until(lambda: not ac.guiSelectedNotes())
