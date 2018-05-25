import json
import urllib2

API_VERSION = 6
API_URL     = 'http://localhost:8765'


def request(action, **params):
    return {'action': action, 'params': params, 'version': API_VERSION}


def invoke(action, **params):
    requestJson = json.dumps(request(action, **params))
    response = json.load(urllib2.urlopen(urllib2.Request(API_URL, requestJson)))
    if len(response) != 2:
        raise Exception('response has an unexpected number of fields')
    if 'error' not in response:
        raise Exception('response is missing required error field')
    if 'result' not in response:
        raise Exception('response is missing required result field')
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']
