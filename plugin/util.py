# Copyright 2016-2026 Alex Yatskov
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

import functools
import os

import aqt


def api():
    """Declare a legacy action; the signature defines its historical parameter binding."""
    def decorator(func):
        @functools.wraps(func)
        def declaration(self, *args, **kwargs):
            func(self, *args, **kwargs)
            raise NotImplementedError('Legacy actions execute through AnkiConnect.handler_async.')
        declaration.api = True
        return declaration

    return decorator


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
    if key not in DEFAULT_CONFIG:
        raise Exception('setting {} not found'.format(key))
    config = aqt.mw.addonManager.getConfig(__name__) or {}
    return config.get(key, DEFAULT_CONFIG[key])


def download(url, limit):
    """Fetch media with Anki's HTTP client, returning at most limit + 1 bytes."""
    from anki.httpclient import HttpClient
    from .protocol import ApiError
    with HttpClient() as client:
        client.timeout = setting('webTimeout') / 1000
        try:
            response = client.get(url)
        except Exception as error:
            raise ApiError('ioError', str(error)) from error
        with response:
            if response.status_code != 200:
                raise ApiError('ioError', '{} download failed with return code {}'.format(url, response.status_code))
            data = bytearray()
            for chunk in response.iter_content(65536):
                data += chunk
                if len(data) > limit:
                    break
            return bytes(data)
