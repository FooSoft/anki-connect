"""Transport-independent RPC, completion and operation state."""
import copy
import time
import uuid
from datetime import datetime, timezone

from .contract import SCHEMA


def timestamp(seconds=None):
    return datetime.fromtimestamp(time.time() if seconds is None else seconds, timezone.utc).isoformat(
        timespec='milliseconds').replace('+00:00', 'Z')


class ApiError(Exception):
    def __init__(self, kind, message, details=None):
        super().__init__(message)
        self.kind = kind
        self.details = details

    def record(self):
        data = {'type': self.kind}
        if self.details is not None:
            data['details'] = self.details
        return {'code': SCHEMA['x-errors'][self.kind], 'message': str(self), 'data': data}


def error_record(exception):
    if isinstance(exception, ApiError):
        return exception.record()
    return ApiError('internalError', 'Internal API error.').record()


class Deferred:
    """Callback completion; never runs a nested Qt event loop."""
    def __init__(self):
        self.done = False
        self.value = None
        self.error = None
        self.callbacks = []

    def resolve(self, value=None, error=None):
        if self.done:
            return
        self.done, self.value, self.error = True, value, error
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            callback(self)

    def then(self, callback):
        if self.done:
            callback(self)
        else:
            self.callbacks.append(callback)
        return self

    def map(self, callback):
        result = Deferred()
        def finish(source):
            if source.error:
                result.resolve(error=source.error)
                return
            try:
                value = callback(source.value)
                if isinstance(value, Deferred):
                    value.then(lambda final: result.resolve(final.value, final.error))
                else:
                    result.resolve(value)
            except Exception as error:
                result.resolve(error=error)
        self.then(finish)
        return result


def completed(value=None, error=None):
    result = Deferred()
    result.resolve(value, error)
    return result


def settle(items):
    """Collect independent replies, preserving their request order."""
    result = Deferred()
    values = [None] * len(items)
    remaining = [len(items)]
    if not items:
        return completed([])
    def finish(index, source):
        values[index] = source.value
        remaining[0] -= 1
        if not remaining[0]:
            result.resolve(values)
    for index, item in enumerate(items):
        item.then(lambda source, index=index: finish(index, source))
    return result


class Operations:
    def __init__(self, schedule, now=time.time):
        self.schedule = schedule
        self.now = now
        self.records = {}
        self.completions = {}
        self.cancellations = {}

    def prune(self):
        limit = SCHEMA['x-limits']
        terminal = sorted((record['updatedAt'], key) for key, record in self.records.items()
                          if record['state'] in ('succeeded', 'failed', 'cancelled'))
        cutoff = timestamp(self.now() - limit['operationRetentionSeconds'])
        excess = max(0, len(terminal) - limit['maxRetainedOperations'])
        for index, (updated, key) in enumerate(terminal):
            if updated < cutoff or index < excess:
                self.records.pop(key, None)
                self.completions.pop(key, None)
                self.cancellations.pop(key, None)

    def submit(self, method, session, start):
        self.prune()
        active = sum(not future.done for future in self.completions.values())
        if active >= SCHEMA['x-limits']['maxActiveOperations']:
            raise ApiError('busy', 'Too many active operations.')
        key = uuid.uuid4().hex
        now = timestamp(self.now())
        self.records[key] = {'operationId': key, 'method': method, 'session': session,
                             'createdAt': now, 'updatedAt': now, 'state': 'queued',
                             'cancellable': True, 'progress': None}
        future = self.completions[key] = Deferred()
        def finish(source):
            if not source.error and method in SCHEMA['x-methods']:
                from jsonschema import Draft202012Validator
                meta = SCHEMA['x-methods'][method]
                schema = meta.get('operationResult', meta['result'])
                if not Draft202012Validator({**SCHEMA, 'oneOf': [schema]}).is_valid(source.value):
                    source = completed(error=ApiError('internalError', 'Operation produced an invalid result.'))
            record = self.records[key]
            record.update(updatedAt=timestamp(self.now()), cancellable=False)
            if source.error:
                record['state'] = 'cancelled' if isinstance(source.error, ApiError) and source.error.kind == 'cancelled' else 'failed'
                record['error'] = error_record(source.error)
            else:
                record.update(state='succeeded', result=source.value)
            self.cancellations.pop(key, None)
            future.resolve(source.value, source.error)
        def run():
            if future.done:
                return
            self.records[key].update(state='running', cancellable=False, updatedAt=timestamp(self.now()))
            try:
                pending = start(key)
                (pending if isinstance(pending, Deferred) else completed(pending)).then(finish)
            except Exception as error:
                finish(completed(error=error))
        self.schedule(run)
        return {'operationId': key, 'method': method, 'session': session}

    def get(self, key):
        self.prune()
        if key not in self.records:
            raise ApiError('notFound', 'Operation not found.')
        return copy.deepcopy(self.records[key])

    def cancel(self, key):
        record = self.get(key)
        if self.completions[key].done:
            return {'requested': False}
        if record['state'] == 'queued':
            error = ApiError('cancelled', 'Operation cancelled before execution.')
            self.records[key].update(state='cancelled', error=error.record(), cancellable=False,
                                      updatedAt=timestamp(self.now()))
            self.completions[key].resolve(error=error)
        elif key in self.cancellations:
            self.cancellations[key]()
        else:
            raise ApiError('unsupportedCapability', 'This operation cannot be cancelled.')
        return {'requested': True}


class Dispatcher:
    def __init__(self, runtime):
        from jsonschema import Draft202012Validator
        self.runtime = runtime
        self.validators = {name: Draft202012Validator({**SCHEMA, 'oneOf': [meta['params']]})
                           for name, meta in SCHEMA['x-methods'].items()}

    def params(self, method, params):
        if method not in self.validators:
            raise ApiError('methodNotFound', 'Unknown method: ' + method)
        errors = sorted(self.validators[method].iter_errors(params), key=lambda e: str(list(e.path)))
        if errors:
            raise ApiError('invalidParams', errors[0].message,
                           {'path': '/' + '/'.join(str(part) for part in errors[0].path)})
        result = copy.deepcopy(params)
        definition = SCHEMA['$defs'][SCHEMA['x-methods'][method]['params']['$ref'].split('/')[-1]]
        for key, value in definition['properties'].items():
            if key not in result and 'default' in value:
                result[key] = copy.deepcopy(value['default'])
        return result

    def invoke(self, method, params):
        return self.runtime.invoke(method, self.params(method, params))

    def request(self, request, context=None):
        context = context or {}
        if isinstance(request, list):
            if not request or len(request) > SCHEMA['x-limits']['maxBatchItems']:
                return completed(self.reply(None, error=ApiError('invalidRequest', 'Invalid batch.')))
            return settle([self.request(item, context) if isinstance(item, dict) else
                           completed(self.reply(None, error=ApiError('invalidRequest', 'Batch items must be request objects.')))
                           for item in request]).map(
                lambda replies: [reply for reply in replies if reply is not None] or None)
        request_id = None
        notification = False
        started = time.monotonic()
        def log(error=None):
            owner = getattr(self.runtime, 'owner', None)
            if owner:
                owner.logEvent('rpc', {'method': request.get('method') if isinstance(request, dict) else None,
                                      'id': request_id, 'durationMs': round((time.monotonic() - started) * 1000),
                                      'error': error.kind if isinstance(error, ApiError) else 'internalError' if error else None})
        try:
            if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str) or not request['method']:
                raise ApiError('invalidRequest', 'Invalid JSON-RPC request.')
            if set(request) - {'jsonrpc', 'id', 'method', 'params'}:
                raise ApiError('invalidRequest', 'Unknown request property.')
            candidate_id = request.get('id')
            if candidate_id is not None and type(candidate_id) not in (str, int):
                raise ApiError('invalidRequest', 'Invalid request ID.')
            request_id = candidate_id
            notification = 'id' not in request
            method = request['method']
            params = self.params(method, request.get('params', {}))
            if notification and SCHEMA['x-methods'][method]['effect'] != 'read':
                log(ApiError('invalidParams', 'Side effects require a request ID.'))
                return completed(None)
            if method == 'access.requestPermission':
                pending = self.runtime.permission(context)
            else:
                pending = self.runtime.invoke(method, params)
            pending = pending if isinstance(pending, Deferred) else completed(pending)
            result = Deferred()
            def finish(source):
                log(source.error)
                result.resolve(None if notification else self.reply(request_id, source.value, source.error))
            pending.then(finish)
            return result
        except Exception as error:
            log(error)
            return completed(None if notification else self.reply(request_id, error=error))

    @staticmethod
    def reply(request_id, value=None, error=None):
        return {'jsonrpc': '2.0', 'id': request_id,
                **({'error': error_record(error)} if error else {'result': value})}
