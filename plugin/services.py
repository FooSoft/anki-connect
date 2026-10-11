"""Native Anki domain services. No legacy action implementations live here."""
import base64
import copy
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from .protocol import ApiError, error_record, timestamp


TYPES = {0: 'new', 1: 'learning', 2: 'review', 3: 'relearning'}
QUEUES = {0: 'new', 1: 'learning', 2: 'review', 3: 'dayLearning', 4: 'preview',
          -1: 'suspended', -2: 'buriedByScheduler', -3: 'buriedByUser'}
RATINGS = ('again', 'hard', 'good', 'easy')
KINDS = ('learning', 'review', 'relearning', 'filtered', 'manual', 'rescheduled')
# Preserve Anki's legacy filename filter without its deprecated stripIllegal API.
MEDIA_ILLEGAL_CHARACTERS = re.compile(r'[][><:"/?*^\\|\0\r\n]')
FIELD_KEYS = {'fontFamily': 'font', 'fontSize': 'size', 'description': 'description',
              'sticky': 'sticky', 'rtl': 'rtl', 'plainText': 'plainText',
              'collapsed': 'collapsed', 'excludeFromSearch': 'excludeFromSearch'}
TEMPLATE_KEYS = {'questionHtml': 'qfmt', 'answerHtml': 'afmt', 'browserQuestionHtml': 'bqfmt',
                 'browserAnswerHtml': 'bafmt', 'browserFontFamily': 'bfont', 'browserFontSize': 'bsize'}
PRESET_KEYS = {
    'learnStepsMinutes': 'learn_steps', 'relearnStepsMinutes': 'relearn_steps',
    'fsrsParameters4': 'fsrs_params_4', 'fsrsParameters5': 'fsrs_params_5', 'fsrsParameters6': 'fsrs_params_6',
    'newPerDay': 'new_per_day', 'newPerDayMinimum': 'new_per_day_minimum',
    'reviewsPerDay': 'reviews_per_day', 'initialEase': 'initial_ease',
    'easyMultiplier': 'easy_multiplier', 'hardMultiplier': 'hard_multiplier', 'lapseMultiplier': 'lapse_multiplier',
    'intervalMultiplier': 'interval_multiplier', 'maximumIntervalDays': 'maximum_review_interval',
    'minimumLapseIntervalDays': 'minimum_lapse_interval', 'graduatingGoodDays': 'graduating_interval_good',
    'graduatingEasyDays': 'graduating_interval_easy', 'leechThreshold': 'leech_threshold',
    'answerTimeLimitSeconds': 'cap_answer_time_to_secs', 'desiredRetention': 'desired_retention',
    'historicalRetention': 'historical_retention', 'easyDaysPercentages': 'easy_days_percentages',
    'ignoreReviewsBefore': 'ignore_revlogs_before_date', 'parameterSearch': 'param_search',
    'questionDisplaySeconds': 'seconds_to_show_question', 'answerDisplaySeconds': 'seconds_to_show_answer',
    'disableAutoplay': 'disable_autoplay', 'showTimer': 'show_timer', 'stopTimerOnAnswer': 'stop_timer_on_answer',
    'waitForAudio': 'wait_for_audio', 'skipQuestionOnAnswerReplay': 'skip_question_when_replaying_answer',
    'buryNew': 'bury_new', 'buryReviews': 'bury_reviews', 'buryDayLearning': 'bury_interday_learning',
}
PRESET_ENUMS = {
    'newInsertOrder': ('new_card_insert_order', ['due', 'random']),
    'newGatherOrder': ('new_card_gather_priority', ['deck', 'lowestPosition', 'highestPosition', 'randomNotes', 'randomCards', 'deckThenRandomNotes']),
    'newSortOrder': ('new_card_sort_order', ['template', 'none', 'templateThenRandom', 'randomNoteThenTemplate', 'randomCard']),
    'reviewOrder': ('review_order', ['day', 'dayThenDeck', 'deckThenDay', 'intervalAscending', 'intervalDescending', 'easeAscending', 'easeDescending', 'retrievabilityAscending', 'random', 'added', 'reverseAdded', 'retrievabilityDescending', 'relativeOverdueness']),
    'newMix': ('new_mix', ['mixed', 'afterReviews', 'beforeReviews']),
    'dayLearningMix': ('interday_learning_mix', ['mixed', 'afterReviews', 'beforeReviews']),
    'leechAction': ('leech_action', ['suspend', 'tagOnly']),
    'questionAction': ('question_action', ['showAnswer', 'showReminder']),
    'answerAction': ('answer_action', ['buryCard', 'again', 'good', 'hard', 'showReminder']),
}


def entity_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value) or int(value) > 9223372036854775807:
        raise ApiError('invalidParams', 'Expected a positive signed 64-bit decimal ID.')
    return int(value)


def interval(value):
    return {'value': abs(value), 'unit': 'seconds' if value < 0 else 'days'}


def normalized_field(value):
    from anki.utils import strip_html_media
    return unicodedata.normalize('NFC', strip_html_media(value))


def template_fields(text, names):
    """Mirror Anki's template tokens; its parsed tree is not exposed to Python."""
    directive = '{{=<% %>=}}'
    if text.lstrip().startswith(directive):
        text = text.lstrip()
        while text.startswith(directive):
            text = text[len(directive):]
        start, end = '<%', '%>'
    else:
        start, end = '{{', '}}'
    pattern = re.compile(re.escape(start) + r'(.*?)' + re.escape(end) + r'|<!--.*?-->', re.S)
    fields, stack = [], []
    for match in pattern.finditer(text):
        if match.group(1) is None:
            continue
        token = match.group(1).lstrip('{').strip()
        if len(token) >= 2 and token[0] in '#^/':
            name = token[1:].lstrip()
            if token[0] == '/':
                if not stack or stack.pop() != name:
                    raise ApiError('validationFailed', 'Mismatched template conditional.')
                continue
            stack.append(name)
        else:
            name = token.rsplit(':', 1)[-1]
        if name in names and name not in fields:
            fields.append(name)
    if stack:
        raise ApiError('validationFailed', 'Unclosed template conditional.')
    return fields


class Services:
    def __init__(self, runtime, collection, session):
        self.runtime, self.col, self.session = runtime, collection, session
        self.changes = []
        self.undo_target = False

    def change(self, result):
        if result is not None:
            self.changes.append(result.changes if hasattr(result, 'changes') else result)
            if self.undo_target is not False:
                if self.undo_target is None:
                    self.undo_target = self.col.undo_status().last_step
                else:
                    self.col.merge_undo_entries(self.undo_target)
        self.runtime.invalidate_predictions()
        return result

    def execute(self, method, params):
        params = dict(params)
        params.pop('session', None)
        handler = getattr(self, method.replace('.', '_'), None)
        if handler is None:
            raise ApiError('unsupportedCapability', 'No verified adapter for ' + method)
        from .contract import SCHEMA
        previous_group = self.undo_target
        if SCHEMA['x-methods'][method]['undo'] in ('single', 'grouped'):
            self.undo_target = None
        try:
            return handler(**params)
        except ApiError:
            raise
        except Exception as error:
            from anki.errors import BackendError, NotFoundError
            if isinstance(error, NotFoundError):
                raise ApiError('notFound', str(error)) from error
            if method in ('packages.import', 'packages.export', 'media.get', 'media.delete') and isinstance(error, (OSError, BackendError)):
                raise ApiError('ioError', str(error)) from error
            raise
        finally:
            self.undo_target = previous_group

    def many(self, values, function, deduplicate=False):
        items, cache = [], {}
        for index, value in enumerate(values):
            key = json.dumps(value, sort_keys=True)
            if deduplicate and key in cache:
                items.append({'index': index, **copy.deepcopy(cache[key])})
                continue
            try:
                entry = {'result': function(value)}
            except Exception as error:
                from anki.errors import NotFoundError
                if isinstance(error, NotFoundError):
                    error = ApiError('notFound', str(error))
                entry = {'error': error_record(error)}
            cache[key] = entry
            items.append({'index': index, **entry})
        return {'items': items}

    def note(self, id):
        return self.col.get_note(entity_id(id))

    def card(self, id):
        return self.col.get_card(entity_id(id))

    def resolve(self, reference, kind):
        manager = self.col.decks if kind == 'deck' else self.col.models
        if 'id' in reference:
            id = entity_id(reference['id'])
            value = manager.get(id, default=False) if kind == 'deck' else manager.get(id)
        else:
            value = manager.by_name(reference['name'])
        if value is None:
            raise ApiError('notFound', kind.title() + ' not found: ' + str(reference))
        return copy.deepcopy(value)

    def summary(self, value):
        return {'id': str(value['id']), 'name': value['name']}

    def collection_get(self):
        return {'profile': self.runtime.profile_name, 'session': self.session,
                'scheduler': 'fsrs' if self.col.get_config('fsrs', False) else 'sm2'}

    def note_record(self, note):
        return {'id': str(note.id), 'noteType': self.summary(note.note_type()),
                'fields': dict(note.items()), 'tags': list(note.tags),
                'cardIds': [str(id) for id in note.card_ids()], 'modifiedAt': timestamp(note.mod)}

    def notes_get(self, id):
        return self.note_record(self.note(id))

    def notes_getMany(self, ids):
        return self.many(ids, self.notes_get)

    def page(self, ids, method, params):
        return self.runtime.page(ids, method, params, self.session)

    def search(self, kind, query, limit=100, cursor=None, sort=None):
        params = {'query': query, 'limit': limit, 'sort': sort}
        if cursor:
            return self.page(None, kind + '.search', {**params, 'cursor': cursor})
        order = False
        if sort:
            from anki.collection import BrowserColumns
            order = self.col.get_browser_column(sort['column'])
            if order is None:
                raise ApiError('invalidParams', 'Unknown browser sort column.')
            sorting = order.sorting_notes if kind == 'notes' else order.sorting_cards
            if sorting == BrowserColumns.SORTING_NONE:
                raise ApiError('invalidParams', 'Browser sort column does not support this search.')
        try:
            finder = self.col.find_notes if kind == 'notes' else self.col.find_cards
            ids = list(finder(query, order=order,
                              reverse=bool(sort and sort['direction'] == 'descending')))
        except Exception as error:
            raise ApiError('invalidSearch', str(error)) from error
        if sort is None:
            ids.sort()
        return self.page(ids, kind + '.search', params)

    def notes_search(self, **params):
        return self.search('notes', **params)

    def cards_search(self, **params):
        return self.search('cards', **params)

    def prepare_note(self, data):
        model = self.resolve(data['noteType'], 'noteType')
        deck = self.resolve(data['deck'], 'deck')
        if deck.get('dyn'):
            raise ApiError('validationFailed', 'Cannot add a note to a filtered deck.')
        note = self.col.new_note(model)
        for name, value in data['fields'].items():
            if name not in note:
                raise ApiError('validationFailed', 'Unknown field: ' + name)
            note[name] = value
        note.tags = list(data.get('tags', []))
        return note, deck

    def empty_questions(self, note):
        from anki.utils import to_json_bytes
        model = note.note_type()
        templates = model['tmpls']
        if model['type'] == 1:
            # Native cloze ordinal enumeration, including fallback card 0.
            ordinals = set(n - 1 for n in self.col._backend.cloze_numbers_in_note(note._to_backend_note())) or {0}
            templates = [{**templates[0], 'ord': index} for index in sorted(ordinals)]
        return all(self.col._backend.render_uncommitted_card_legacy(
            note=note._to_backend_note(), card_ord=template['ord'], template=to_json_bytes(template),
            fill_empty=False, partial_render=True).is_empty for template in templates)

    def validation(self, note, deck, policy, reject_empty):
        result = int(note.fields_check())
        reasons = {1: 'emptyFirstField', 3: 'missingCloze', 4: 'notClozeNoteType', 5: 'notClozeField'}
        issues = []
        if result in reasons:
            issues.append({'type': reasons[result], 'message': 'Anki field validation: ' + reasons[result]})
        elif result not in (0, 2):
            raise ApiError('unsupportedCapability', 'Unknown native field validation result.')
        duplicates = []
        policy = policy or {}
        source = normalized_field(note.fields[0])
        if not policy.get('allow', False):
            from anki.utils import field_checksum
            candidates = self.col.db.list('select id from notes where csum=? and id!=?', field_checksum(note.fields[0]), note.id)
            scope_decks = None
            if policy.get('scope', 'collection') == 'deck':
                target = self.resolve(policy.get('deck', self.summary(deck)), 'deck')
                scope_decks = {target['id']}
                if policy.get('includeChildren', False):
                    scope_decks.update(id for _, id in self.col.decks.children(target['id']))
            for id in candidates:
                other = self.col.get_note(id)
                if not policy.get('acrossNoteTypes', False) and other.mid != note.mid:
                    continue
                if normalized_field(other.fields[0]) != source:
                    continue
                if scope_decks is not None and not any((card.odid or card.did) in scope_decks for card in other.cards()):
                    continue
                duplicates.append(str(id))
            if duplicates:
                issues.append({'type': 'duplicate', 'message': 'A matching note exists.'})
        if reject_empty and not issues and self.empty_questions(note):
            issues.append({'type': 'emptyQuestions', 'message': 'All generated questions are empty.'})
        return {'valid': not issues, 'issues': issues, 'duplicateNoteIds': duplicates}

    def notes_validate(self, note):
        native, deck = self.prepare_note(note)
        return self.validation(native, deck, note.get('duplicates'), note.get('rejectEmptyQuestions', True))

    def notes_validateMany(self, notes):
        return self.many(notes, self.notes_validate)

    def notes_create(self, **data):
        note, deck = self.prepare_note(data)
        validation = self.validation(note, deck, data.get('duplicates'), data.get('rejectEmptyQuestions', True))
        if not validation['valid']:
            raise ApiError('validationFailed', 'Note cannot be created.', validation)
        self.change(self.col.add_note(note, deck['id']))
        return {'noteId': str(note.id), 'cardIds': [str(id) for id in note.card_ids()]}

    def notes_createMany(self, notes, atomic=False):
        if not atomic:
            return self.many(notes, lambda data: self.notes_create(**data))
        from anki.collection import AddNoteRequest
        prepared, errors, seen = [], [], []
        for index, data in enumerate(notes):
            try:
                note, deck = self.prepare_note(data)
                validation = self.validation(note, deck, data.get('duplicates'), data.get('rejectEmptyQuestions', True))
                policy = data.get('duplicates', {})
                if not policy.get('allow', False):
                    for old_note, old_deck in seen:
                        if normalized_field(note.fields[0]) != normalized_field(old_note.fields[0]):
                            continue
                        if not policy.get('acrossNoteTypes', False) and old_note.mid != note.mid:
                            continue
                        if policy.get('scope') == 'deck':
                            scoped = self.resolve(policy.get('deck', self.summary(deck)), 'deck')['id']
                            dids = {scoped}
                            if policy.get('includeChildren'):
                                dids.update(did for _, did in self.col.decks.children(scoped))
                            if old_deck['id'] not in dids:
                                continue
                        validation['valid'] = False
                        validation['issues'].append({'type': 'duplicate', 'message': 'Duplicate within batch.'})
                if not validation['valid']:
                    raise ApiError('validationFailed', 'Invalid note.', validation)
                prepared.append(AddNoteRequest(note=note, deck_id=deck['id']))
                seen.append((note, deck))
            except Exception as error:
                errors.append({'index': index, 'error': error_record(error)})
        if errors:
            raise ApiError('validationFailed', 'Atomic batch validation failed.', {'items': errors})
        if prepared:
            self.change(self.col.add_notes(prepared))
        return {'items': [{'index': index, 'result': {'noteId': str(req.note.id), 'cardIds': [str(id) for id in req.note.card_ids()]}}
                          for index, req in enumerate(prepared)]}

    def notes_update(self, id, patch):
        note = self.note(id)
        for name, value in patch.get('fields', {}).items():
            if name not in note:
                raise ApiError('validationFailed', 'Unknown field: ' + name)
            note[name] = value
        if 'tags' in patch:
            note.tags = patch['tags']
        self.change(self.col.update_note(note))
        return self.note_record(self.note(id))

    def notes_delete(self, ids):
        def delete(id):
            self.note(id)
            self.change(self.col.remove_notes([entity_id(id)]))
            return {'changed': True}
        return self.many(ids, delete, True)

    def notes_planConversion(self, source, target):
        old, new = self.resolve(source, 'noteType'), self.resolve(target, 'noteType')
        info = self.col.models.change_notetype_info(old_notetype_id=old['id'], new_notetype_id=new['id'])
        def maps(key, indices):
            return [{'target': item['name'], 'source': old[key][index]['name'] if index >= 0 else None}
                    for item, index in zip(new[key], indices)]
        return {'source': self.summary(old), 'target': self.summary(new),
                'fields': maps('flds', info.input.new_fields), 'templates': maps('tmpls', info.input.new_templates),
                'token': self.runtime.token('conversion', [old, new])}

    def notes_convert(self, ids, target, fields, templates, planToken):
        if not ids:
            return {'changedCount': 0}
        notes = [self.note(id) for id in ids]
        old = copy.deepcopy(notes[0].note_type())
        new = self.resolve(target, 'noteType')
        if any(note.mid != old['id'] for note in notes):
            raise ApiError('validationFailed', 'Conversion requires one source note type.')
        self.runtime.check_token(planToken, 'conversion', [old, new])
        info = self.col.models.change_notetype_info(old_notetype_id=old['id'], new_notetype_id=new['id'])
        def indices(mapping, key):
            if key == 'tmpls' and info.input.is_cloze:
                if mapping:
                    raise ApiError('invalidParams', 'Native cloze conversion requires an empty template map.')
                return []
            by_name = {entry['target']: entry['source'] for entry in mapping}
            if len(by_name) != len(mapping) or set(by_name) != {item['name'] for item in new[key]}:
                raise ApiError('invalidParams', 'Mappings must cover every target once.')
            source_names = [item['name'] for item in old[key]]
            chosen = [by_name[item['name']] for item in new[key]]
            used = [name for name in chosen if name is not None]
            if len(used) != len(set(used)) or any(name not in source_names for name in used):
                raise ApiError('invalidParams', 'Invalid/duplicate source mapping.')
            return [source_names.index(name) if name is not None else -1 for name in chosen]
        request = info.input
        request.note_ids.extend(entity_id(id) for id in ids)
        request.new_fields[:] = indices(fields, 'flds')
        request.new_templates[:] = indices(templates, 'tmpls')
        self.change(self.col.models.change_notetype_of_notes(request))
        return {'changedCount': len(set(ids))}

    def notes_findEmpty(self, criterion, query='', limit=100, cursor=None):
        params = {'criterion': criterion, 'query': query, 'limit': limit}
        if cursor:
            return self.page(None, 'notes.findEmpty', {**params, 'cursor': cursor})
        matches = []
        for id in self.col.find_notes(query):
            note = self.col.get_note(id)
            if ((criterion == 'noCards' and not note.card_ids()) or
                (criterion == 'allFieldsEmpty' and all(not normalized_field(value).strip() for value in note.fields)) or
                (criterion == 'allQuestionsEmpty' and self.empty_questions(note))):
                matches.append(id)
        return self.page(sorted(matches), 'notes.findEmpty', params)

    def tags_list(self):
        return list(self.col.tags.all())

    def mutate_tags(self, noteIds, tags, remove):
        def mutate(id):
            note = self.note(id)
            before = list(note.tags)
            for tag in tags:
                note.remove_tag(tag) if remove else note.add_tag(tag)
            if before != note.tags:
                self.change(self.col.update_note(note))
            return {'changed': before != note.tags}
        return self.many(noteIds, mutate, True)

    def tags_add(self, noteIds, tags):
        return self.mutate_tags(noteIds, tags, False)

    def tags_remove(self, noteIds, tags):
        return self.mutate_tags(noteIds, tags, True)

    def tags_replace(self, **params):
        ids = params.get('noteIds') if 'noteIds' in params else [str(id) for id in self.col.find_notes('')]
        changed = []
        for id in set(ids):
            note = self.note(id)
            if note.has_tag(params['from']):
                note.remove_tag(params['from'])
                note.add_tag(params['to'])
                changed.append(note)
        if changed:
            self.change(self.col.update_notes(changed))
        return {'changedCount': len(changed)}

    def tags_deleteUnused(self):
        out = self.change(self.col.tags.clear_unused_tags())
        return {'changedCount': out.count}

    def state_record(self, card):
        queue = QUEUES.get(card.queue)
        if queue is None or card.type not in TYPES:
            raise ApiError('unsupportedCapability', 'Unknown card scheduling state.')
        underlying = card.queue if card.queue >= 0 else card.type
        if underlying == 0:
            due = {'kind': 'position', 'position': max(0, card.due)}
        elif card.queue in (1, 4) or (card.queue < 0 and card.type in (1, 3) and card.due > 1000000000):
            due = {'kind': 'timestamp', 'at': timestamp(card.due)}
        else:
            due = {'kind': 'day', 'day': card.due}
        seconds = None
        if card.type in (1, 3):
            states = self.col._backend.get_scheduling_states(card.id)
            native = states.current.normal
            if states.current.WhichOneof('kind') == 'filtered' and states.current.filtered.WhichOneof('kind') == 'rescheduling':
                native = states.current.filtered.rescheduling.original_state
            kind = native.WhichOneof('kind')
            if kind == 'learning':
                seconds = native.learning.scheduled_secs
            elif kind == 'relearning':
                seconds = native.relearning.learning.scheduled_secs
        memory = card.memory_state
        return {'type': TYPES[card.type], 'queue': queue, 'due': due, 'intervalDays': card.ivl,
                'learningIntervalSeconds': seconds, 'remainingSteps': card.left, 'repetitions': card.reps,
                'lapses': card.lapses, 'sm2EasePermille': card.factor,
                'fsrsMemory': {'difficulty': memory.difficulty, 'stabilityDays': memory.stability} if memory else None,
                'desiredRetention': card.desired_retention}

    def card_record(self, card):
        return {'id': str(card.id), 'noteId': str(card.nid), 'deck': self.summary(self.resolve({'id': str(card.did)}, 'deck')),
                'homeDeck': self.summary(self.resolve({'id': str(card.odid)}, 'deck')) if card.odid else None,
                'templateIndex': card.ord, 'flags': card.flags & 7, 'modifiedAt': timestamp(card.mod),
                'scheduling': self.state_record(card)}

    def cards_get(self, id):
        return self.card_record(self.card(id))

    def cards_getMany(self, ids):
        return self.many(ids, self.cards_get)

    def cards_render(self, id):
        card = self.card(id)
        return {'cardId': id, 'questionHtml': card.question(), 'answerHtml': card.answer(), 'css': card.note_type()['css']}

    def cards_move(self, ids, deck):
        target = self.resolve(deck, 'deck')
        if target.get('dyn'):
            raise ApiError('invalidState', 'Filtered decks cannot be move destinations.')
        def move(id):
            card = self.card(id)
            changed = bool(card.odid or card.did != target['id'])
            if changed:
                self.change(self.col.set_deck([card.id], target['id']))
            return {'changed': changed}
        return self.many(ids, move, True)

    def cards_setSuspended(self, ids, suspended):
        def mutate(id):
            card = self.card(id)
            changed = (card.queue == -1) != suspended
            if changed:
                operation = self.col.sched.suspend_cards if suspended else self.col.sched.unsuspend_cards
                self.change(operation([card.id]))
            return {'changed': changed}
        return self.many(ids, mutate, True)

    def cards_setFlags(self, ids, flag):
        def mutate(id):
            card = self.card(id)
            changed = card.flags & 7 != flag
            if changed:
                self.change(self.col.set_user_flag_for_cards(flag, [card.id]))
            return {'changed': changed}
        return self.many(ids, mutate, True)

    def scheduling_get(self, cardId):
        return self.state_record(self.card(cardId))

    def scheduling_predict(self, cardId):
        card = self.card(cardId)
        states = self.col._backend.get_scheduling_states(card.id)
        labels = self.col._backend.describe_next_states(states)
        answers = []
        for rating, label in zip(RATINGS, labels):
            state = getattr(states, rating)
            native = state.normal
            if state.WhichOneof('kind') == 'filtered':
                if state.filtered.WhichOneof('kind') == 'preview':
                    amount = {'value': state.filtered.preview.scheduled_secs, 'unit': 'seconds'}
                    answers.append({'rating': rating, 'label': label, 'interval': amount})
                    continue
                native = state.filtered.rescheduling.original_state
            kind = native.WhichOneof('kind')
            if kind == 'review':
                amount = {'value': native.review.scheduled_days, 'unit': 'days'}
            elif kind == 'learning':
                amount = {'value': native.learning.scheduled_secs, 'unit': 'seconds'}
            elif kind == 'relearning':
                amount = {'value': native.relearning.learning.scheduled_secs, 'unit': 'seconds'}
            else:
                amount = None
            answers.append({'rating': rating, 'label': label, 'interval': amount})
        token = self.runtime.token('scheduler', [card._to_backend_card().SerializeToString().hex(), states.SerializeToString().hex(), self.col.sched.today])
        return {'cardId': cardId, 'source': 'scheduler', 'stateToken': token, 'answers': answers}

    def scheduling_getDue(self, cardId, includeLearnAhead=False):
        card = self.card(cardId)
        now = time.time()
        due = False
        ahead = False
        if card.queue in (1, 4):
            due = card.due <= now
            ahead = not due and card.due <= now + self.col.get_config('collapseTime', 1200)
        elif card.queue in (2, 3):
            due = card.due <= self.col.sched.today
        return {'cardId': cardId, 'dueNow': due, 'available': due or card.queue == 0 or (includeLearnAhead and ahead), 'learnAhead': ahead}

    def scheduling_answer(self, cardId, rating, stateToken, elapsedMs=0):
        from anki.scheduler.v3 import CardAnswer
        card = self.card(cardId)
        if card.queue < 0 or card.queue == 4:
            raise ApiError('invalidState', 'This card cannot be answered outside the reviewer.')
        if self.runtime.active_reviewer_card == card.id:
            raise ApiError('invalidState', 'Use reviewer.answer for the active GUI card.')
        states = self.col._backend.get_scheduling_states(card.id)
        self.runtime.check_token(stateToken, 'scheduler', [card._to_backend_card().SerializeToString().hex(), states.SerializeToString().hex(), self.col.sched.today])
        card.start_timer()
        native_rating = {'again': CardAnswer.AGAIN, 'hard': CardAnswer.HARD,
                         'good': CardAnswer.GOOD, 'easy': CardAnswer.EASY}[rating]
        answer = self.col.sched.build_answer(card=card, states=states, rating=native_rating)
        maximum = card.time_limit()
        answer.milliseconds_taken = min(elapsedMs, maximum)
        self.change(self.col.sched.answer_card(answer))
        review_id = self.col.db.scalar('select max(id) from revlog where cid=?', card.id)
        return {'cardId': cardId, 'reviewId': str(review_id) if review_id else None, 'scheduling': self.state_record(self.card(cardId))}

    def scheduling_answerMany(self, answers):
        return self.many(answers, lambda data: self.scheduling_answer(**data))

    def scheduling_reset(self, cardIds, restorePosition=True, resetCounts=False, log=True):
        from anki.scheduler.base import ScheduleCardsAsNew
        def reset(id):
            card = self.card(id)
            self.change(self.col._backend.schedule_cards_as_new(ScheduleCardsAsNew(
                card_ids=[card.id], restore_position=restorePosition, reset_counts=resetCounts, log=log)))
            return {'changed': True}
        return self.many(cardIds, reset, True)

    def scheduling_setDueDate(self, cardIds, days):
        def set_due(id):
            card = self.card(id)
            self.change(self.col.sched.set_due_date([card.id], days, config_key=None))
            return {'changed': True}
        return self.many(cardIds, set_due, True)

    def deck_record(self, deck):
        return {**self.summary(deck), 'kind': 'filtered' if deck.get('dyn') else 'normal',
                'presetId': str(deck['conf']) if not deck.get('dyn') else None}

    def decks_list(self):
        return [self.decks_get({'id': str(deck.id)}) for deck in self.col.decks.all_names_and_ids()]

    def decks_get(self, deck):
        return self.deck_record(self.resolve(deck, 'deck'))

    def decks_create(self, name):
        out = self.change(self.col.decks.add_normal_deck_with_name(name))
        return self.decks_get({'id': str(out.id)})

    def decks_update(self, deck, name):
        value = self.resolve(deck, 'deck')
        other = self.col.decks.id_for_name(name)
        if other and other != value['id']:
            raise ApiError('conflict', 'A deck with this name exists.')
        self.change(self.col.decks.rename(value['id'], name))
        return self.decks_get({'id': str(value['id'])})

    def decks_delete(self, decks, deleteCards):
        def delete(reference):
            value = self.resolve(reference, 'deck')
            self.change(self.col.decks.remove([value['id']]))
            return {'changed': True}
        return self.many(decks, delete, True)

    def decks_getCounts(self, deck, includeChildren=True):
        value = self.resolve(deck, 'deck')
        def find(node):
            if node.deck_id == value['id']:
                return node
            for child in node.children:
                match = find(child)
                if match:
                    return match
        node = find(self.col.sched.deck_due_tree())
        if not node:
            raise ApiError('notFound', 'Deck counts unavailable.')
        counts = [node.new_count, node.learn_count, node.review_count]
        if not includeChildren:
            for child in node.children:
                counts = [max(0, a - b) for a, b in zip(counts, [child.new_count, child.learn_count, child.review_count])]
        dids = [value['id']] + ([id for _, id in self.col.decks.children(value['id'])] if includeChildren else [])
        total = sum(self.col.db.scalar('select count(*) from cards where did=?', id) for id in dids)
        return {'deckId': str(value['id']), **dict(zip(['new', 'learning', 'review'], counts)), 'total': total}

    def noteTypes_list(self):
        return [{'id': str(value.id), 'name': value.name} for value in self.col.models.all_names_and_ids()]

    def type_record(self, model):
        fields = []
        for field in model['flds']:
            fields.append({'name': field['name'], **{public: field.get(native, '' if public == 'description' else False)
                                                    for public, native in FIELD_KEYS.items()}})
        templates = []
        for template in model['tmpls']:
            templates.append({'name': template['name'], **{public: (template.get(native) or (20 if public == 'browserFontSize' else 'Arial' if public == 'browserFontFamily' else ''))
                                                          for public, native in TEMPLATE_KEYS.items()},
                              'deck': {'id': str(template['did'])} if template.get('did') else None})
        return {**self.summary(model), 'kind': 'cloze' if model['type'] else 'normal', 'fields': fields,
                'templates': templates, 'css': model['css'], 'sortField': model['flds'][model['sortf']]['name'],
                'latexHeader': model.get('latexPre', ''), 'latexFooter': model.get('latexPost', ''),
                'latexSvg': bool(model.get('latexsvg', False)), 'modifiedAt': timestamp(model['mod'])}

    def noteTypes_get(self, noteType):
        return self.type_record(self.resolve(noteType, 'noteType'))

    def fill_field(self, target, source):
        target['name'] = source.get('name', target['name'])
        for public, native in FIELD_KEYS.items():
            if public in source:
                target[native] = source[public]

    def fill_template(self, target, source):
        target['name'] = source.get('name', target['name'])
        for public, native in TEMPLATE_KEYS.items():
            if public in source:
                target[native] = source[public]
        if 'deck' in source:
            target['did'] = self.resolve(source['deck'], 'deck')['id'] if source['deck'] else None

    def noteTypes_create(self, name, fields, templates, kind='normal', css='', sortField=None, latexHeader='', latexFooter='', latexSvg=False):
        if self.col.models.by_name(name):
            raise ApiError('conflict', 'Note type already exists.')
        model = self.col.models.new(name)
        model.update(type=int(kind == 'cloze'), css=css, latexPre=latexHeader, latexPost=latexFooter, latexsvg=latexSvg)
        for data in fields:
            field = self.col.models.new_field(data['name'])
            self.fill_field(field, data)
            self.col.models.add_field(model, field)
        for data in templates:
            template = self.col.models.new_template(data['name'])
            self.fill_template(template, data)
            self.col.models.add_template(model, template)
        names = [field['name'] for field in model['flds']]
        if len(names) != len(set(names)) or len({t['name'] for t in model['tmpls']}) != len(templates):
            raise ApiError('validationFailed', 'Duplicate field/template names.')
        model['sortf'] = names.index(sortField) if sortField else 0
        out = self.change(self.col.models.add_dict(model))
        return self.noteTypes_get({'id': str(out.id)})

    def noteTypes_update(self, noteType, patch):
        model = self.resolve(noteType, 'noteType')
        mapping = {'name': 'name', 'css': 'css', 'latexHeader': 'latexPre', 'latexFooter': 'latexPost', 'latexSvg': 'latexsvg'}
        if 'name' in patch:
            other = self.col.models.by_name(patch['name'])
            if other and other['id'] != model['id']:
                raise ApiError('conflict', 'Note type name exists.')
        for key, value in patch.items():
            if key == 'sortField':
                names = [field['name'] for field in model['flds']]
                if value not in names:
                    raise ApiError('validationFailed', 'Sort field not found.')
                model['sortf'] = names.index(value)
            else:
                model[mapping[key]] = value
        self.change(self.col.models.update_dict(model))
        return self.noteTypes_get({'id': str(model['id'])})

    def noteTypes_editStructure(self, noteType, edits):
        model = self.resolve(noteType, 'noteType')
        for edit in edits:
            is_field = edit['op'].endswith('Field')
            key = 'flds' if is_field else 'tmpls'
            values = model[key]
            verb = edit['op'].replace('Field' if is_field else 'Template', '')
            if verb == 'add':
                data = edit['field' if is_field else 'template']
                value = self.col.models.new_field(data['name']) if is_field else self.col.models.new_template(data['name'])
                (self.fill_field if is_field else self.fill_template)(value, data)
                index = edit.get('index', len(values))
                if index > len(values):
                    raise ApiError('validationFailed', 'Insertion index out of range.')
                values.insert(index, value)
            else:
                value = next((value for value in values if value['name'] == edit['name']), None)
                if value is None:
                    raise ApiError('notFound', 'Field/template not found.')
                if verb == 'update':
                    patch = edit['patch']
                    if is_field and 'name' in patch:
                        self.col.models.rename_field(model, value, patch['name'])
                    (self.fill_field if is_field else self.fill_template)(value, patch)
                elif verb == 'remove':
                    values.remove(value)
                elif verb == 'move':
                    if edit['index'] >= len(values):
                        raise ApiError('validationFailed', 'Move index out of range.')
                    values.remove(value)
                    values.insert(edit['index'], value)
            if not values or len({value['name'] for value in values}) != len(values):
                raise ApiError('validationFailed', 'Invalid field/template structure.')
        self.change(self.col.models.update_dict(model))
        return self.noteTypes_get({'id': str(model['id'])})

    def noteTypes_getTemplateUsage(self, noteType):
        model = self.resolve(noteType, 'noteType')
        names = {field['name'] for field in model['flds']}
        result = []
        for template in model['tmpls']:
            fields = [template_fields(template[key], names) for key in ('qfmt', 'afmt')]
            result.append({'templateName': template['name'], 'questionFields': fields[0], 'answerFields': fields[1]})
        return result

    def noteTypes_replaceText(self, find, replace, noteTypes=None, allNoteTypes=False, targets=('question', 'answer', 'css')):
        references = noteTypes if noteTypes is not None else self.noteTypes_list()
        changed = 0
        for reference in references:
            model = self.resolve(reference, 'noteType')
            before = copy.deepcopy(model)
            if 'css' in targets:
                model['css'] = model['css'].replace(find, replace)
            for template in model['tmpls']:
                for target, key in [('question', 'qfmt'), ('answer', 'afmt')]:
                    if target in targets:
                        template[key] = template[key].replace(find, replace)
            if model != before:
                self.change(self.col.models.update_dict(model))
                changed += 1
        return {'changedCount': changed}

    def noteTypes_deleteUnused(self, noteTypes):
        def delete(reference):
            model = self.resolve(reference, 'noteType')
            if self.col.models.use_count(model['id']):
                raise ApiError('conflict', 'Note type is in use.')
            self.change(self.col.models.remove(model['id']))
            return {'changed': True}
        return self.many(noteTypes, delete, True)

    def preset(self, reference):
        values = self.col.decks.all_config()
        value = next((value for value in values if str(value['id']) == reference.get('id') or value['name'] == reference.get('name')), None)
        if value is None:
            raise ApiError('notFound', 'Preset not found.')
        return self.col._backend.get_deck_config(value['id'])

    def preset_record(self, config):
        settings = {}
        for public, native in PRESET_KEYS.items():
            value = getattr(config.config, native)
            settings[public] = list(value) if config.config.DESCRIPTOR.fields_by_name[native].is_repeated else value
        for public, (native, names) in PRESET_ENUMS.items():
            settings[public] = names[getattr(config.config, native)]
        return {'id': str(config.id), 'name': config.name, 'settings': settings, 'modifiedAt': timestamp(config.mtime_secs)}

    def deckPresets_list(self):
        return [self.summary(value) for value in self.col.decks.all_config()]

    def deckPresets_get(self, preset):
        return self.preset_record(self.preset(preset))

    def preset_update_request(self, deck_id, configs=(), remove=(), reschedule=False):
        from anki.decks import UpdateDeckConfigs
        current = self.col.decks.get_deck_configs_for_update(deck_id)
        return UpdateDeckConfigs(target_deck_id=deck_id, configs=configs, removed_config_ids=remove,
                                 mode=0, limits=current.current_deck.limits,
                                 card_state_customizer=current.card_state_customizer,
                                 new_cards_ignore_review_limit=current.new_cards_ignore_review_limit,
                                 fsrs=current.fsrs, apply_all_parent_limits=current.apply_all_parent_limits,
                                 fsrs_reschedule=reschedule, fsrs_health_check=current.fsrs_health_check)

    def deckPresets_create(self, name, cloneFrom=None):
        if any(value['name'] == name for value in self.col.decks.all_config()):
            raise ApiError('conflict', 'Preset already exists.')
        current = self.col.decks.get_deck_configs_for_update(1)
        config = copy.deepcopy(self.preset(cloneFrom) if cloneFrom else current.defaults)
        config.id, config.name = 0, name
        # Updating configs selects the last one: include the previously selected
        # preset last so cloning does not change the Default deck's assignment.
        selected = self.preset({'id': str(current.current_deck.config_id)})
        self.change(self.col.decks.update_deck_configs(self.preset_update_request(1, [config, selected])))
        return self.deckPresets_get({'name': name})

    def deckPresets_update(self, preset, name=None, settings=None, rescheduleFsrs=False):
        config = copy.deepcopy(self.preset(preset))
        if name:
            config.name = name
        for public, value in (settings or {}).items():
            if public in PRESET_ENUMS:
                native, names = PRESET_ENUMS[public]
                setattr(config.config, native, names.index(value))
            else:
                native = PRESET_KEYS[public]
                destination = getattr(config.config, native)
                if isinstance(value, list):
                    destination[:] = value
                else:
                    setattr(config.config, native, value)
        current = self.col.decks.get_deck_configs_for_update(1)
        selected = self.preset({'id': str(current.current_deck.config_id)})
        configs = [config] if selected.id == config.id else [config, selected]
        self.change(self.col.decks.update_deck_configs(self.preset_update_request(1, configs, reschedule=rescheduleFsrs)))
        return self.deckPresets_get({'id': str(config.id)})

    def deckPresets_assign(self, decks, preset, rescheduleFsrs=False):
        config = self.preset(preset)
        def assign(reference):
            deck = self.resolve(reference, 'deck')
            if deck.get('dyn'):
                raise ApiError('invalidState', 'Filtered decks have no preset.')
            changed = deck['conf'] != config.id
            if changed:
                self.change(self.col.decks.update_deck_configs(self.preset_update_request(deck['id'], [config], reschedule=rescheduleFsrs)))
            return {'changed': changed}
        return self.many(decks, assign, True)

    def deckPresets_delete(self, preset, replacement=None):
        config = self.preset(preset)
        if config.id == 1:
            raise ApiError('conflict', 'Cannot delete the Default preset.')
        dependent = [deck for deck in self.decks_list() if deck['presetId'] == str(config.id)]
        if dependent and replacement is None:
            raise ApiError('conflict', 'An in-use preset needs a replacement.')
        if replacement:
            chosen = self.preset(replacement)
            if chosen.id == config.id:
                raise ApiError('conflict', 'Replacement is the preset being deleted.')
            for deck in dependent:
                self.change(self.col.decks.update_deck_configs(self.preset_update_request(int(deck['id']), [chosen])))
        selected = self.preset({'id': str(self.resolve({'id': '1'}, 'deck')['conf'])})
        self.change(self.col.decks.update_deck_configs(self.preset_update_request(1, [selected], [config.id])))
        return {'changed': True}

    def media_filename(self, filename):
        if filename in ('.', '..') or any(char in filename for char in ('/', '\\', '\0')):
            raise ApiError('invalidParams', 'Expected a media basename.')
        return MEDIA_ILLEGAL_CHARACTERS.sub('', unicodedata.normalize('NFC', filename))

    def media_list(self, pattern='*'):
        import fnmatch
        self.media_filename(pattern)
        return sorted(name for name in os.listdir(self.col.media.dir()) if fnmatch.fnmatchcase(name, pattern))

    def media_get(self, filename):
        filename = self.media_filename(filename)
        path = Path(self.col.media.dir()) / filename
        if not path.is_file():
            raise ApiError('notFound', 'Media file not found.')
        return {'filename': filename, 'data': base64.b64encode(path.read_bytes()).decode('ascii')}

    def media_delete(self, filename):
        filename = self.media_filename(filename)
        if not (Path(self.col.media.dir()) / filename).is_file():
            raise ApiError('notFound', 'Media file not found.')
        self.col.media.trash_files([filename])
        return {'changed': True}

    def media_getDirectory(self):
        return {'path': os.path.abspath(self.col.media.dir())}

    def store_bytes(self, filename, data, collision='rename', skipIfHash=None):
        if collision != 'replace':
            from anki.errors import BackendError
            try:
                return self._store_bytes(filename, data, collision, skipIfHash)
            except (OSError, BackendError) as error:
                raise ApiError('ioError', str(error)) from error
        from .media import MediaTransaction
        transaction = MediaTransaction(self)
        try:
            actual = transaction.install(filename, data, skipIfHash, collision)
            transaction.commit()
            return {'filename': actual, 'status': 'skipped' if actual is None else 'stored',
                    'sha256': hashlib.sha256(data).hexdigest()}
        except Exception as error:
            failures = transaction.rollback()
            if isinstance(error, ApiError) and not failures:
                raise
            raise ApiError('ioError', 'Media replacement failed.', {'rollbackFailures': failures}) from error

    def _store_bytes(self, filename, data, collision='rename', skipIfHash=None):
        filename = self.media_filename(filename)
        sha = hashlib.sha256(data).hexdigest()
        if skipIfHash and hashlib.new(skipIfHash['algorithm'], data).hexdigest() == skipIfHash['digest']:
            return {'filename': None, 'status': 'skipped', 'sha256': sha}
        path = Path(self.col.media.dir()) / filename
        if path.exists():
            if collision == 'error':
                raise ApiError('conflict', 'Media filename already exists.')
            if collision == 'replace' and path.read_bytes() != data:
                # Replacement callers journal the original before this native write.
                self.col.media.trash_files([filename])
        actual = self.col.media.write_data(filename, data)
        return {'filename': actual, 'status': 'stored', 'sha256': sha}

    def review_ids(self, cardIds=None, deck=None, includeChildren=False, membership='current', afterId=None, includeManual=True):
        clauses, args = [], []
        if cardIds is not None:
            for id in cardIds:
                self.card(id)
            clauses.append('cid in (' + ','.join('?' for _ in cardIds) + ')')
            args.extend(entity_id(id) for id in cardIds)
        if deck:
            value = self.resolve(deck, 'deck')
            dids = [value['id']]
            if includeChildren:
                dids.extend(id for _, id in self.col.decks.children(value['id']))
            column = '(case when odid!=0 then odid else did end)' if membership == 'home' else 'did'
            clauses.append('cid in (select id from cards where ' + column + ' in (' + ','.join('?' for _ in dids) + '))')
            args.extend(dids)
        if afterId:
            clauses.append('id>?')
            args.append(entity_id(afterId))
        if not includeManual:
            clauses.append('type not in (4,5)')
        sql = 'select id from revlog' + (' where ' + ' and '.join(clauses) if clauses else '') + ' order by id'
        return self.col.db.list(sql, *args)

    def review_record(self, id):
        row = self.col.db.first('select id,cid,usn,ease,ivl,lastIvl,factor,time,type from revlog where id=?', id)
        if not row:
            return None
        id, cid, usn, ease, ivl, last, factor, elapsed, kind = row
        return {'id': str(id), 'cardId': str(cid), 'answeredAt': timestamp(id / 1000),
                'rating': RATINGS[ease - 1] if 1 <= ease <= 4 else None, 'interval': interval(ivl),
                'previousInterval': interval(last), 'factor': {'encoding': 'unknown', 'value': factor},
                'elapsedMs': elapsed, 'kind': KINDS[kind], 'syncSequence': usn}

    def reviews_list(self, limit=100, cursor=None, **params):
        ids = None if cursor else self.review_ids(**params)
        page = self.page(ids, 'reviews.list', {**params, 'limit': limit, 'cursor': cursor})
        return {'items': [value for id in page['ids'] if (value := self.review_record(int(id)))], 'nextCursor': page['nextCursor']}

    def reviews_getLatestId(self, **params):
        ids = self.review_ids(**params)
        return {'id': str(ids[-1]) if ids else None}

    def statistics_getToday(self):
        graphs = self.col._backend.graphs(search='', days=0)
        cutoff = self.col.sched.day_cutoff
        return {'count': graphs.today.answer_count, 'day': datetime.fromtimestamp(cutoff - 86400).date().isoformat(), 'nextDayAt': timestamp(cutoff)}

    def statistics_getReviewDays(self):
        graphs = self.col._backend.graphs(search='', days=0)
        today = datetime.fromtimestamp(self.col.sched.day_cutoff - 86400).date()
        return [{'day': (today + timedelta(days=offset)).isoformat(),
                 'count': counts.learn + counts.relearn + counts.young + counts.mature + counts.filtered}
                for offset, counts in sorted(graphs.reviews.count.items(), reverse=True)]

    def statistics_getSummary(self, deck=None):
        query = self.col.build_search_string(__import__('anki.collection', fromlist=['SearchNode']).SearchNode(deck=self.resolve(deck, 'deck')['name'])) if deck else ''
        graphs = self.col._backend.graphs(search=query, days=0)
        counts = graphs.card_counts.excluding_inactive
        card_ids = self.col.find_cards(query)
        note_ids = {self.col.get_card(id).nid for id in card_ids}
        review_count = sum(value.learn + value.relearn + value.young + value.mature + value.filtered for value in graphs.reviews.count.values())
        times = sum(value.learn + value.relearn + value.young + value.mature + value.filtered for value in graphs.reviews.time.values())
        return {'cardCount': len(card_ids), 'noteCount': len(note_ids), 'reviewCount': review_count,
                'reviewTimeMs': times * 1000, 'newCount': counts.newCards, 'learningCount': counts.learn + counts.relearn,
                'reviewCardCount': counts.young + counts.mature, 'suspendedCount': counts.suspended}

    def statistics_getHtml(self, deck=None):
        stats = self.col.stats()
        stats.wholeCollection = deck is None
        if deck:
            # Legacy HTML stats binds its deck explicitly; never change selected deck as a read.
            stats.did = self.resolve(deck, 'deck')['id']
        return {'html': stats.report(), 'format': 'legacyReport'}

    def packages_import(self, path):
        from anki.collection import ImportAnkiPackageRequest, ImportAnkiPackageOptions
        if not os.path.isfile(path):
            raise ApiError('notFound', 'Package not found.')
        self.change(self.col.import_anki_package(ImportAnkiPackageRequest(
            package_path=path, options=ImportAnkiPackageOptions(
                merge_notetypes=True, with_scheduling=True, with_deck_configs=True))))
        return {'completed': True}

    def packages_export(self, deck, path, includeScheduling=False):
        from anki.collection import ExportAnkiPackageOptions, DeckIdLimit
        self.col.export_anki_package(out_path=path, options=ExportAnkiPackageOptions(
            with_scheduling=includeScheduling, with_media=True, legacy=True),
            limit=DeckIdLimit(deck_id=self.resolve(deck, 'deck')['id']))
        return {'path': os.path.abspath(path)}

    def advanced_cards_update(self, cardId, patch):
        card = self.card(cardId)
        if any(key in patch for key in ('remainingSteps', 'fsrsMemory')):
            raise ApiError('unsupportedCapability', 'Coupled scheduler state must use native scheduling transitions.')
        mapping = {'intervalDays': 'ivl', 'sm2EasePermille': 'factor', 'repetitions': 'reps', 'lapses': 'lapses', 'customData': 'custom_data'}
        for key, value in patch.items():
            if key == 'customData':
                try:
                    if not isinstance(json.loads(value or '{}'), dict):
                        raise ValueError('Expected object')
                except ValueError as error:
                    raise ApiError('validationFailed', 'Custom data must encode a JSON object.') from error
            if key == 'sm2EasePermille' and not 1300 <= value <= 65535:
                raise ApiError('validationFailed', 'SM-2 ease must be between 1300 and 65535 permille.')
            setattr(card, mapping[key], value)
        self.change(self.col.update_card(card))
        return self.card_record(self.card(cardId))

    def advanced_reviews_import(self, reviews):
        rows, ids = [], set()
        for review in reviews:
            id = entity_id(review['id'])
            cid = self.card(review['cardId']).id
            if id in ids or self.col.db.scalar('select 1 from revlog where id=?', id):
                raise ApiError('conflict', 'Review ID already exists.')
            ids.add(id)
            def encoded(value):
                amount = value['value']
                if amount > 2147483647:
                    raise ApiError('validationFailed', 'Interval exceeds native limits.')
                return -amount if value['unit'] == 'seconds' else amount
            ease = RATINGS.index(review['rating']) + 1 if review['rating'] else 0
            factor, elapsed = review['factor']['value'], review['elapsedMs']
            if factor > 65535 or elapsed > 2147483647:
                raise ApiError('validationFailed', 'Review metadata exceeds native limits.')
            rows.append((id, cid, -1, ease, encoded(review['interval']), encoded(review['previousInterval']),
                         factor, elapsed, KINDS.index(review['kind'])))
        if rows:
            self.col.db.transact(lambda: self.col.db.executemany(
                'insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type) values (?,?,?,?,?,?,?,?,?)', rows))
            self.runtime.full_reset_required = True
            self.runtime.invalidate_predictions()
        return {'changedCount': len(rows)}

    def collection_undo(self):
        status = self.col.undo_status()
        if not status.undo:
            raise ApiError('invalidState', 'Nothing to undo.')
        self.change(self.col.undo())
        return {'label': status.undo, 'changed': True}

    def collection_checkIntegrity(self):
        report, ok = self.col.fix_integrity()
        self.runtime.full_reset_required = True
        return {'problems': [] if ok else [report], 'repaired': bool(ok)}
