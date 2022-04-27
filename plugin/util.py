# Copyright 2016-2021 Alex Yatskov
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
import sys

import anki
import anki.sync
import aqt
import enum

#
# Utilities
#

class MediaType(enum.Enum):
    Audio = 1
    Video = 2
    Picture = 3


def download(url):
    client = anki.sync.AnkiRequestsClient()
    client.timeout = setting('webTimeout') / 1000

    resp = client.get(url)
    if resp.status_code != 200:
        raise Exception('{} download failed with return code {}'.format(url, resp.status_code))

    return client.streamContent(resp)


def api(*versions):
    def decorator(func):
        setattr(func, 'versions', versions)
        setattr(func, 'api', True)
        return func

    return decorator


def cardQuestion(card):
    if getattr(card, 'question', None) is None:
        return card._getQA()['q']

    return card.question()


def cardAnswer(card):
    if getattr(card, 'answer', None) is None:
        return card._getQA()['a']

    return card.answer()


DEFAULT_CONFIG = {
    'apiKey': None,
    'apiLogPath': None,
    'apiPollInterval': 25,
    'apiVersion': 6,
    'webBacklog': 5,
    'webBindAddress': os.getenv('ANKICONNECT_BIND_ADDRESS', '127.0.0.1'),
    'webBindPort': 8765,
    'webCorsOrigin': os.getenv('ANKICONNECT_CORS_ORIGIN', None),
    'webCorsOriginList': ['http://localhost'],
    'ignoreOriginList': [],
    'webTimeout': 10000,
}

def setting(key):
    try:
        return aqt.mw.addonManager.getConfig(__name__).get(key, DEFAULT_CONFIG[key])
    except:
        raise Exception('setting {} not found'.format(key))


# see https://github.com/FooSoft/anki-connect/issues/308
# fixed in https://github.com/ankitects/anki/commit/0b2a226d
def patch_anki_2_1_50_having_null_stdout_on_windows():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf8")
