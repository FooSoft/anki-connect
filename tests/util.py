import json
import urllib
import urllib2

def callAnkiConnectEndpoint(data):
    url = 'http://docker:8888'
    dumpedData = json.dumps(data)
    req = urllib2.Request(url, dumpedData)
    response = urllib2.urlopen(req).read()
    responseData = json.loads(response)
    return responseData