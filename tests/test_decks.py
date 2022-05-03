import pytest

from conftest import ac


def test_deckNames(session_with_profile_loaded):
    result = ac.deckNames()
    assert result == ["Default"]


def test_deckNamesAndIds(session_with_profile_loaded):
    result = ac.deckNamesAndIds()
    assert result == {"Default": 1}


def test_createDeck(session_with_profile_loaded):
    ac.createDeck("foo")
    assert {*ac.deckNames()} == {"Default", "foo"}


def test_changeDeck(setup):
    ac.changeDeck(cards=setup.card_ids, deck="bar")
    assert "bar" in ac.deckNames()


def test_deleteDeck(setup):
    before = ac.deckNames()
    ac.deleteDecks(decks=["test_deck"], cardsToo=True)
    after = ac.deckNames()
    assert {*before} - {*after} == {"test_deck"}


def test_deleteDeck_must_be_called_with_cardsToo_set_to_True_on_later_api(setup):
    with pytest.raises(Exception):
        ac.deleteDecks(decks=["test_deck"])
    with pytest.raises(Exception):
        ac.deleteDecks(decks=["test_deck"], cardsToo=False)


def test_getDeckConfig(session_with_profile_loaded):
    result = ac.getDeckConfig(deck="Default")
    assert result["name"] == "Default"


def test_saveDeckConfig(session_with_profile_loaded):
    config = ac.getDeckConfig(deck="Default")
    result = ac.saveDeckConfig(config=config)
    assert result is True


def test_setDeckConfigId(session_with_profile_loaded):
    result = ac.setDeckConfigId(decks=["Default"], configId=1)
    assert result is True


def test_cloneDeckConfigId(session_with_profile_loaded):
    result = ac.cloneDeckConfigId(cloneFrom=1, name="test")
    assert isinstance(result, int)


def test_removedDeckConfigId(session_with_profile_loaded):
    new_config_id = ac.cloneDeckConfigId(cloneFrom=1, name="test")
    assert ac.removeDeckConfigId(configId=new_config_id) is True


def test_removedDeckConfigId_fails_with_invalid_id(session_with_profile_loaded):
    new_config_id = ac.cloneDeckConfigId(cloneFrom=1, name="test")
    assert ac.removeDeckConfigId(configId=new_config_id) is True
    assert ac.removeDeckConfigId(configId=new_config_id) is False


def test_getDeckStats(session_with_profile_loaded):
    result = ac.getDeckStats(decks=["Default"])
    assert result["name"] == "Default"
