import pytest
from anki.errors import NotFoundError  # noqa

from conftest import ac


def test_findCards(setup):
    card_ids = ac.findCards(query="deck:test_deck")
    assert len(card_ids) == 4


class TestEaseFactors:
    def test_setEaseFactors(self, setup):
        result = ac.setEaseFactors(cards=setup.card_ids, easeFactors=[4200] * 4)
        assert result == [True] * 4

    def test_setEaseFactors_with_invalid_card_id(self, setup):
        result = ac.setEaseFactors(cards=[123], easeFactors=[4200])
        assert result == [False]

    def test_getEaseFactors(self, setup):
        ac.setEaseFactors(cards=setup.card_ids, easeFactors=[4200] * 4)
        result = ac.getEaseFactors(cards=setup.card_ids)
        assert result == [4200] * 4

    def test_getEaseFactors_with_invalid_card_id(self, setup):
        assert ac.getEaseFactors(cards=[123]) == [None]


class TestSuspending:
    def test_suspend(self, setup):
        assert ac.suspend(cards=setup.card_ids) is True

    def test_suspend_fails_with_incorrect_id(self, setup):
        with pytest.raises(NotFoundError):
            assert ac.suspend(cards=[123])

    def test_areSuspended_returns_False_for_regular_cards(self, setup):
        result = ac.areSuspended(cards=setup.card_ids)
        assert result == [False] * 4

    def test_areSuspended_returns_True_for_suspended_cards(self, setup):
        ac.suspend(setup.card_ids)
        result = ac.areSuspended(cards=setup.card_ids)
        assert result == [True] * 4


def test_areDue_returns_True_for_new_cards(setup):
    result = ac.areDue(cards=setup.card_ids)
    assert result == [True] * 4


def test_getIntervals(setup):
    ac.getIntervals(cards=setup.card_ids, complete=False)
    ac.getIntervals(cards=setup.card_ids, complete=True)


def test_cardsToNotes(setup):
    result = ac.cardsToNotes(cards=setup.card_ids)
    assert {*result} == {setup.note1_id, setup.note2_id}


class TestCardInfo:
    def test_with_valid_ids(self, setup):
        result = ac.cardsInfo(cards=setup.card_ids)
        assert [item["cardId"] for item in result] == setup.card_ids

    def test_with_incorrect_id(self, setup):
        result = ac.cardsInfo(cards=[123])
        assert result == [{}]


def test_forgetCards(setup):
    ac.forgetCards(cards=setup.card_ids)


def test_relearnCards(setup):
    ac.relearnCards(cards=setup.card_ids)


class TestAnswerCards:
    def test_answerCards(self, setup):
        ac.scheduler().reset()
        result = ac.answerCards(cards=setup.card_ids, answers=[2, 1, 4, 3])
        assert result == [True] * 4

    def test_answerCards_with_invalid_card_id(self, setup):
        ac.scheduler().reset()
        result = ac.answerCards(cards=[123], answers=[2])
        assert result == [False]
