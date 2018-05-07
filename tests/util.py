import json
import urllib2


def request(action, params={}, version=5):
    return {'action': action, 'params': params, 'version': version}


def invoke(action, params={}, version=5, url='http://localhost:8765'):
    requestJson = json.dumps(request(action, params, version))
    response = json.load(urllib2.urlopen(urllib2.Request(url, requestJson)))
    return response['result'], response['error']


def invokeNoError(action, params={}, version=5, url='http://localhost:8765'):
    result, error = invoke(action, params, version, url)
    if error is not None:
        raise Exception(error)
    return result
