"""New-card repositioning against disposable native Anki collections."""
import pytest

from plugin.protocol import ApiError
from tests_api.test_runtime import call, native


def new_cards(service, count=3):
    return [call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                 fields={'Front': str(index)})['cardIds'][0] for index in range(count)]


def positions(service, ids):
    return [service.col.get_card(int(id)).due for id in ids]


def test_reposition_to_front_preserves_state_queue_and_undo(native):
    owner, service = native
    ids = new_cards(service)
    before = positions(service, ids)
    target = service.col.get_card(int(ids[-1]))
    state = (target.type, target.queue, target.ivl, target.reps, target.lapses, target.odue, target.odid)
    assert call(service, 'scheduling.repositionNewCards', cardIds=[ids[-1], ids[-1]],
                startingFrom=0) == {'changedCount': 1}
    assert positions(service, ids) == before[:-1] + [0]
    target = service.col.get_card(int(ids[-1]))
    assert (target.type, target.queue, target.ivl, target.reps, target.lapses, target.odue, target.odid) == state
    assert service.col.db.scalar('select count() from revlog') == 0
    assert call(service, 'scheduling.getQueue', fetchLimit=1)['cards'][0]['cardId'] == ids[-1]
    call(service, 'collection.undo')
    assert positions(service, ids) == before


def test_reposition_order_step_shift_and_single_undo(native):
    owner, service = native
    ids = new_cards(service, 4)
    before = positions(service, ids)
    result = call(service, 'scheduling.repositionNewCards', cardIds=[ids[3], ids[2]],
                  startingFrom=1, stepSize=2, shiftExisting=True)
    assert result == {'changedCount': 2}
    assert positions(service, ids[2:]) == [3, 1]
    assert positions(service, ids[:2]) == [5, 6]
    call(service, 'collection.undo')
    assert positions(service, ids) == before


def test_reposition_siblings_share_native_note_position(native):
    owner, service = native
    note = call(service, 'notes.create', noteType={'name': 'Basic (and reversed card)'},
                deck={'name': 'Default'}, fields={'Front': 'siblings', 'Back': 'answer'})
    ids = note['cardIds']
    assert len(ids) == 2
    assert call(service, 'scheduling.repositionNewCards', cardIds=ids,
                startingFrom=5, stepSize=2)['changedCount'] == 2
    assert positions(service, ids) == [5, 5]


@pytest.mark.parametrize('state', ['learning', 'review', 'suspended', 'buried', 'filtered'])
def test_reposition_rejects_invalid_state_before_any_changes(native, state):
    owner, service = native
    ids = new_cards(service)
    card = service.col.get_card(int(ids[-1]))
    if state == 'learning':
        card.type, card.queue = 1, 1
    elif state == 'review':
        card.type, card.queue = 2, 2
    elif state == 'suspended':
        card.queue = -1
    elif state == 'buried':
        card.queue = -2
    else:
        card.odid, card.odue = card.did, card.due
        card.did = service.col.decks.new_filtered('Filtered')
    service.col.update_card(card)
    before = positions(service, ids)
    with pytest.raises(ApiError) as caught:
        call(service, 'scheduling.repositionNewCards', cardIds=ids, startingFrom=0)
    assert caught.value.kind == 'invalidState'
    assert positions(service, ids) == before


def test_reposition_missing_card_does_not_move_existing_cards(native):
    owner, service = native
    ids = new_cards(service)
    before = positions(service, ids)
    with pytest.raises(ApiError) as caught:
        call(service, 'scheduling.repositionNewCards', cardIds=ids + ['999'], startingFrom=0)
    assert caught.value.kind == 'notFound'
    assert positions(service, ids) == before


def test_reposition_position_overflow_does_not_change_cards(native):
    owner, service = native
    ids = new_cards(service)
    before = positions(service, ids)
    with pytest.raises(ApiError) as caught:
        call(service, 'scheduling.repositionNewCards', cardIds=ids, startingFrom=2147483647)
    assert caught.value.kind == 'invalidParams'
    assert positions(service, ids) == before


@pytest.mark.parametrize('state', ['new', 'suspended', 'buried', 'filtered'])
@pytest.mark.parametrize('step, due', [(1, 2147483647), (2147483647, 1)])
def test_reposition_shift_overflow_does_not_change_cards(native, state, step, due):
    owner, service = native
    ids = new_cards(service)
    card = service.col.get_card(int(ids[0]))
    card.due = due
    if state == 'suspended':
        card.queue = -1
    elif state == 'buried':
        card.queue = -2
    elif state == 'filtered':
        card.odid, card.odue = card.did, card.due
        card.did = service.col.decks.new_filtered('Filtered')
    else:
        card.did = service.col.decks.id('Other')
    service.col.update_card(card)
    before = service.col.db.all('select id, due, odue from cards order by id')
    # Before 2.1.45 there is no undo status to compare.
    undo_status = getattr(service.col, 'undo_status', lambda: None)
    undo = undo_status()
    generation = service.runtime.generation
    with pytest.raises(ApiError) as caught:
        call(service, 'scheduling.repositionNewCards', cardIds=[ids[-1]],
             startingFrom=0, stepSize=step, shiftExisting=True)
    assert caught.value.kind == 'invalidParams'
    assert service.col.db.all('select id, due, odue from cards order by id') == before
    assert undo_status() == undo
    assert service.runtime.generation == generation


def test_reposition_shift_counts_siblings_before_checking_overflow(native):
    owner, service = native
    existing = new_cards(service, 1)
    card = service.col.get_card(int(existing[0]))
    card.due = 2147483644
    service.col.update_card(card)
    siblings = call(service, 'notes.create', noteType={'name': 'Basic (and reversed card)'},
                    deck={'name': 'Default'}, fields={'Front': 'siblings', 'Back': 'answer'})['cardIds']
    before = positions(service, existing + siblings)
    with pytest.raises(ApiError) as caught:
        call(service, 'scheduling.repositionNewCards', cardIds=siblings,
             startingFrom=0, stepSize=2, shiftExisting=True)
    assert caught.value.kind == 'invalidParams'
    assert positions(service, existing + siblings) == before


def test_reposition_allows_boundary_positions_and_safe_shifts(native):
    owner, service = native
    ids = new_cards(service)
    assert call(service, 'scheduling.repositionNewCards', cardIds=[ids[0]],
                startingFrom=2147483646) == {'changedCount': 1}
    before = positions(service, ids)
    assert call(service, 'scheduling.repositionNewCards', cardIds=[ids[-1], ids[-1]],
                startingFrom=0, shiftExisting=True) == {'changedCount': 1}
    assert positions(service, ids) == [2147483647, before[1] + 1, 0]
    call(service, 'collection.undo')
    assert positions(service, ids) == before
    assert call(service, 'scheduling.repositionNewCards', cardIds=[ids[-1]],
                startingFrom=2147483647) == {'changedCount': 1}
    assert positions(service, ids)[-1] == 2147483647


def test_reposition_randomized_notes_keep_steps_and_siblings_together(native):
    owner, service = native
    notes = [call(service, 'notes.create', noteType={'name': 'Basic (and reversed card)'},
                  deck={'name': 'Default'}, fields={'Front': str(index), 'Back': 'answer'})
             for index in range(4)]
    ids = [id for note in notes for id in note['cardIds']]
    before = positions(service, ids)
    assert call(service, 'scheduling.repositionNewCards', cardIds=ids,
                startingFrom=5, stepSize=3, randomize=True) == {'changedCount': 8}
    assigned = [positions(service, note['cardIds']) for note in notes]
    assert all(first == second for first, second in assigned)
    assert sorted(first for first, second in assigned) == [5, 8, 11, 14]
    call(service, 'collection.undo')
    assert positions(service, ids) == before
