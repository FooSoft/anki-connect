import json
import urllib2


def request(action, params={}, version=5):
    return {'action': action, 'params': params, 'version': version}


def invoke(action, params={}, version=5, url='http://localhost:8765'):
    requestJson = json.dumps(request(action, params, version))
    response = json.load(urllib2.urlopen(urllib2.Request(url, requestJson)))
    if len(response) != 2:
        raise Exception('response has an unexpected number of fields')
    if 'error' not in response:
        raise Exception('response is missing required error field')
    if 'result' not in response:
        raise Exception('response is missing required result field')
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']
