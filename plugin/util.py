# Copyright 2016-2020 Alex Yatskov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import os

import anki
import anki.sync
import aqt


#
# Utilities
#

def download(url):
    client = anki.sync.AnkiRequestsClient()
    client.timeout = setting('webTimeout') / 1000
    resp = client.get(url)
    if resp.status_code == 200:
        return client.streamContent(resp)
    else:
        raise Exception('{} download failed with return code {}'.format(url, resp.status_code))


def api(*versions):
    def decorator(func):
        method = lambda *args, **kwargs: func(*args, **kwargs)
        setattr(method, 'versions', versions)
        setattr(method, 'api', True)
        return method

    return decorator


def getQuestion(card):
    if getattr(card, 'question', None) is None:
        question = card._getQA()['q']
    else:
        question = card.question(),
    return question


def getAnswer(card):
    if getattr(card, 'answer', None) is None:
        answer = card._getQA()['a']
    else:
        answer = card.answer()
    return answer


def setting(key):
    defaults = {
        'apiKey': None,
        'apiLogPath': None,
        'apiPollInterval': 25,
        'apiVersion': 6,
        'webBacklog': 5,
        'webBindAddress': os.getenv('ANKICONNECT_BIND_ADDRESS', '127.0.0.1'),
        'webBindPort': 8765,
        'webCorsOrigin': os.getenv('ANKICONNECT_CORS_ORIGIN', 'http://localhost'),
        'webCorsOriginList': ['http://localhost'],
        'webTimeout': 10000,
    }

    try:
        return aqt.mw.addonManager.getConfig(__name__).get(key, defaults[key])
    except:
        raise Exception('setting {} not found'.format(key))
