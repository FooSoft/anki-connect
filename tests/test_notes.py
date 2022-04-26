import pytest
from anki.errors import NotFoundError  # noqa

from conftest import ac


def make_note(*, front="front1", allow_duplicates=False):
    note = {
        "deckName": "test_deck",
        "modelName": "Basic",
        "fields": {"Front": front, "Back": "back1"},
        "tags": ["tag1"],
    }

    if allow_duplicates:
        return {**note, "options": {"allowDuplicate": True}}
    else:
        return note


##############################################################################


class TestNoteAddition:
    def test_addNote(self, setup):
        result = ac.addNote(note=make_note())
        assert isinstance(result, int)

    def test_addNote_will_not_allow_duplicates_by_default(self, setup):
        ac.addNote(make_note())
        with pytest.raises(Exception, match="it is a duplicate"):
            ac.addNote(make_note())

    def test_addNote_will_allow_duplicates_if_options_say_aye(self, setup):
        ac.addNote(make_note())
        ac.addNote(make_note(allow_duplicates=True))

    def test_addNotes(self, setup):
        result = ac.addNotes(notes=[
            make_note(front="foo"),
            make_note(front="bar"),
            make_note(front="foo"),
        ])

        assert len(result) == 3
        assert isinstance(result[0], int)
        assert isinstance(result[1], int)
        assert result[2] is None

    def test_bug164(self, setup):
        note = {
            "deckName": "test_deck",
            "modelName": "Basic",
            "fields": {"Front": " Whitespace\n", "Back": ""},
            "options": {"allowDuplicate": False, "duplicateScope": "deck"}
        }

        ac.addNote(note=note)
        with pytest.raises(Exception, match="it is a duplicate"):
            ac.addNote(note=note)


def test_notesInfo(setup):
    result = ac.notesInfo(notes=[setup.note1_id])
    assert len(result) == 1
    assert result[0]["noteId"] == setup.note1_id
    assert result[0]["tags"] == ["tag1"]
    assert result[0]["fields"]["field1"]["value"] == "note1 field1"


class TestTags:
    def test_addTags(self, setup):
        ac.addTags(notes=[setup.note1_id], tags="tag2")
        tags = ac.notesInfo(notes=[setup.note1_id])[0]["tags"]
        assert {*tags} == {"tag1", "tag2"}

    def test_getTags(self, setup):
        result = ac.getTags()
        assert {*result} == {"tag1", "tag2"}

    def test_removeTags(self, setup):
        ac.removeTags(notes=[setup.note2_id], tags="tag2")
        assert ac.notesInfo(notes=[setup.note2_id])[0]["tags"] == []

    def test_replaceTags(self, setup):
        ac.replaceTags(notes=[setup.note1_id, 123],
                       tag_to_replace="tag1", replace_with_tag="foo")
        notes_info = ac.notesInfo(notes=[setup.note1_id])
        assert notes_info[0]["tags"] == ["foo"]

    def test_replaceTagsInAllNotes(self, setup):
        ac.replaceTagsInAllNotes(tag_to_replace="tag1", replace_with_tag="foo")
        notes_info = ac.notesInfo(notes=[setup.note1_id])
        assert notes_info[0]["tags"] == ["foo"]

    def test_clearUnusedTags(self, setup):
        ac.removeTags(notes=[setup.note2_id], tags="tag2")
        ac.clearUnusedTags()
        assert ac.getTags() == ["tag1"]


class TestUpdateNoteFields:
    def test_updateNoteFields(self, setup):
        new_fields = {"field1": "foo", "field2": "bar"}
        good_note = {"id": setup.note1_id, "fields": new_fields}
        ac.updateNoteFields(note=good_note)
        notes_info = ac.notesInfo(notes=[setup.note1_id])
        assert notes_info[0]["fields"]["field2"]["value"] == "bar"

    def test_updateNoteFields_will_note_update_invalid_notes(self, setup):
        bad_note = {"id": 123, "fields": make_note()["fields"]}
        with pytest.raises(NotFoundError):
            ac.updateNoteFields(note=bad_note)


class TestCanAddNotes:
    foo_bar_notes = [make_note(front="foo"), make_note(front="bar")]

    def test_canAddNotes(self, setup):
        result = ac.canAddNotes(notes=self.foo_bar_notes)
        assert result == [True, True]

    def test_canAddNotes_will_not_add_duplicates_if_options_do_not_say_aye(self, setup):
        ac.addNotes(notes=self.foo_bar_notes)
        notes = [
            make_note(front="foo"),
            make_note(front="baz"),
            make_note(front="foo", allow_duplicates=True)
        ]
        result = ac.canAddNotes(notes=notes)
        assert result == [False, True, True]


def test_findNotes(setup):
    result = ac.findNotes(query="deck:test_deck")
    assert {*result} == {setup.note1_id, setup.note2_id}


def test_deleteNotes(setup):
    ac.deleteNotes(notes=[setup.note1_id, setup.note2_id])
    result = ac.findNotes(query="deck:test_deck")
    assert result == []
