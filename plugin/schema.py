"""Draft 2020-12 validation for the API contract across bundled jsonschema releases.

Anki bundled jsonschema 3.2 (no Draft 2020-12) through 2.1.49 and 4.1 (no
local ``$ref`` resolution under a URN ``$id``) through 25.02. Those releases use
this validator, which implements the subset of keywords the contract uses.
"""
import re

try:
    import referencing  # noqa: F401 - jsonschema 4.18 resolves references through it.
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

ANNOTATIONS = {'$schema', '$id', '$defs', '$comment', 'title', 'description', 'default',
               'examples', 'format', 'contentEncoding', 'contentMediaType', 'deprecated',
               'readOnly', 'writeOnly'}


class ValidationError(Exception):
    def __init__(self, message, path=(), context=()):
        super().__init__(message)
        self.message = message
        self.path = list(path)
        self.context = list(context)


def equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def is_type(instance, kind):
    number = isinstance(instance, (int, float)) and not isinstance(instance, bool)
    return {
        'object': isinstance(instance, dict),
        'array': isinstance(instance, list),
        'string': isinstance(instance, str),
        'boolean': isinstance(instance, bool),
        'null': instance is None,
        'number': number,
        'integer': number and (isinstance(instance, int) or instance.is_integer()),
    }[kind]


class Validator:
    def __init__(self, schema):
        self.root = schema
        self.patterns = {}

    def resolve(self, reference):
        if not reference.startswith('#'):
            raise ValueError('Unsupported reference: ' + reference)
        target = self.root
        for part in reference[1:].split('/')[1:]:
            target = target[part.replace('~1', '/').replace('~0', '~')]
        return target

    def is_valid(self, instance):
        return not self.check(self.root, instance, [])[0]

    def iter_errors(self, instance):
        return iter(self.check(self.root, instance, [])[0])

    def search(self, pattern, text):
        if pattern not in self.patterns:
            self.patterns[pattern] = re.compile(pattern)
        return self.patterns[pattern].search(text)

    def check(self, schema, instance, path):
        """Return the errors and the object keys evaluated by successful subschemas."""
        if schema is True:
            return [], set()
        if schema is False:
            return [ValidationError('False schema does not allow {!r}'.format(instance), path)], set()
        errors, evaluated = [], set()
        def fail(message, context=()):
            errors.append(ValidationError(message, path, context))
        def apply(subschema):
            return self.check(subschema, instance, path)
        if '$ref' in schema:
            found, keys = apply(self.resolve(schema['$ref']))
            errors += found
            evaluated |= keys
        if 'type' in schema:
            kinds = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
            if not any(is_type(instance, kind) for kind in kinds):
                fail('{!r} is not of type {}'.format(instance, ', '.join(repr(kind) for kind in kinds)))
        if 'const' in schema and not equal(instance, schema['const']):
            fail('{!r} was expected'.format(schema['const']))
        if 'enum' in schema and not any(equal(instance, value) for value in schema['enum']):
            fail('{!r} is not one of {!r}'.format(instance, schema['enum']))
        if is_type(instance, 'number'):
            for keyword, failed, message in (
                    ('minimum', lambda bound: instance < bound, 'is less than the minimum of'),
                    ('maximum', lambda bound: instance > bound, 'is greater than the maximum of'),
                    ('exclusiveMinimum', lambda bound: instance <= bound, 'is less than or equal to the minimum of'),
                    ('exclusiveMaximum', lambda bound: instance >= bound, 'is greater than or equal to the maximum of')):
                if keyword in schema and failed(schema[keyword]):
                    fail('{!r} {} {!r}'.format(instance, message, schema[keyword]))
        if isinstance(instance, str):
            if len(instance) < schema.get('minLength', 0):
                fail('{!r} is too short'.format(instance))
            if 'maxLength' in schema and len(instance) > schema['maxLength']:
                fail('{!r} is too long'.format(instance))
            if 'pattern' in schema and not self.search(schema['pattern'], instance):
                fail('{!r} does not match {!r}'.format(instance, schema['pattern']))
        if isinstance(instance, list):
            if len(instance) < schema.get('minItems', 0):
                fail('{!r} is too short'.format(instance))
            if 'maxItems' in schema and len(instance) > schema['maxItems']:
                fail('{!r} is too long'.format(instance))
            if schema.get('uniqueItems') and any(equal(instance[i], instance[j]) for i in range(len(instance))
                                                 for j in range(i + 1, len(instance))):
                fail('{!r} has non-unique elements'.format(instance))
            if 'items' in schema:
                for index, item in enumerate(instance):
                    errors += self.check(schema['items'], item, path + [index])[0]
        if isinstance(instance, dict):
            for name in schema.get('required', []):
                if name not in instance:
                    fail('{!r} is a required property'.format(name))
            if len(instance) < schema.get('minProperties', 0):
                fail('{!r} does not have enough properties'.format(instance))
            if 'maxProperties' in schema and len(instance) > schema['maxProperties']:
                fail('{!r} has too many properties'.format(instance))
            for name, required in schema.get('dependentRequired', {}).items():
                if name in instance:
                    for other in required:
                        if other not in instance:
                            fail('{!r} is a dependency of {!r}'.format(other, name))
            properties = schema.get('properties', {})
            for name, subschema in properties.items():
                if name in instance:
                    evaluated.add(name)
                    errors += self.check(subschema, instance[name], path + [name])[0]
            matched = set()
            for pattern, subschema in schema.get('patternProperties', {}).items():
                for name in instance:
                    if self.search(pattern, name):
                        matched.add(name)
                        errors += self.check(subschema, instance[name], path + [name])[0]
            evaluated |= matched
            if 'propertyNames' in schema:
                for name in instance:
                    errors += self.check(schema['propertyNames'], name, path)[0]
            if 'additionalProperties' in schema:
                extra = [name for name in instance if name not in properties and name not in matched]
                evaluated.update(extra)
                if schema['additionalProperties'] is False and extra:
                    fail('Additional properties are not allowed ({} {} unexpected)'.format(
                        ', '.join(repr(name) for name in extra), 'was' if len(extra) == 1 else 'were'))
                elif schema['additionalProperties'] is not False:
                    for name in extra:
                        errors += self.check(schema['additionalProperties'], instance[name], path + [name])[0]
        for subschema in schema.get('allOf', []):
            found, keys = apply(subschema)
            errors += found
            evaluated |= keys
        if 'anyOf' in schema:
            outcomes = [apply(subschema) for subschema in schema['anyOf']]
            if all(found for found, _ in outcomes):
                fail('{!r} is not valid under any of the given schemas'.format(instance),
                     [error for found, _ in outcomes for error in found])
            for found, keys in outcomes:
                if not found:
                    evaluated |= keys
        if 'oneOf' in schema:
            outcomes = [apply(subschema) for subschema in schema['oneOf']]
            valid = [keys for found, keys in outcomes if not found]
            if not valid:
                fail('{!r} is not valid under any of the given schemas'.format(instance),
                     [error for found, _ in outcomes for error in found])
            elif len(valid) > 1:
                fail('{!r} is valid under each of {}'.format(instance, ', '.join(
                    repr(subschema) for subschema, (found, _) in zip(schema['oneOf'], outcomes) if not found)))
            else:
                evaluated |= valid[0]
        if 'not' in schema and not apply(schema['not'])[0]:
            fail('{!r} should not be valid under {!r}'.format(instance, schema['not']))
        if 'if' in schema:
            found, keys = apply(schema['if'])
            branch = 'else' if found else 'then'
            if not found:
                evaluated |= keys
            if branch in schema:
                found, keys = apply(schema[branch])
                errors += found
                if not found:
                    evaluated |= keys
        if 'unevaluatedProperties' in schema and isinstance(instance, dict):
            extra = [name for name in instance if name not in evaluated]
            if schema['unevaluatedProperties'] is False and extra:
                fail('Unevaluated properties are not allowed ({} {} unexpected)'.format(
                    ', '.join(repr(name) for name in extra), 'was' if len(extra) == 1 else 'were'))
            elif schema['unevaluatedProperties'] is not False:
                for name in extra:
                    errors += self.check(schema['unevaluatedProperties'], instance[name], path + [name])[0]
            evaluated.update(instance)
        unknown = set(schema) - KEYWORDS - ANNOTATIONS
        if unknown and not all(keyword.startswith('x-') for keyword in unknown):
            raise ValueError('Unsupported schema keywords: ' + ', '.join(sorted(unknown)))
        return errors, evaluated if not errors else set()


KEYWORDS = {'$ref', 'type', 'const', 'enum', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
            'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems', 'uniqueItems', 'items', 'required',
            'minProperties', 'maxProperties', 'dependentRequired', 'properties', 'patternProperties',
            'propertyNames', 'additionalProperties', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else',
            'unevaluatedProperties'}


def validator(schema):
    """Return a Draft 2020-12 validator with ``is_valid`` and ``iter_errors``."""
    if Draft202012Validator is not None:
        return Draft202012Validator(schema)
    return Validator(schema)
