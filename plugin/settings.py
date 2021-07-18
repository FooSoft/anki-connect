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
import aqt


def query(key):
    defaults = {
        'apiKey': None,
        'apiPollInterval': 25,
        'webBindAddress': os.getenv('ANKICONNECT_BIND_ADDRESS', '127.0.0.1'),
        'webBindPort': 8765,
        'webCorsOrigin': os.getenv('ANKICONNECT_CORS_ORIGIN'),
        'webCorsOriginList': [],
        'webTimeout': 10000,
    }

    try:
        value = aqt.mw.addonManager.getConfig(__name__).get(key, defaults[key])
    except:
        raise Exception('setting {} not found'.format(key))

    if key == 'webCorsOriginList':
        originOld = query('webCorsOrigin')
        if originOld:
            value.append(originOld)

        value += [
            'http://127.0.0.1:',
            'http://localhost:',
            'chrome-extension://',
            'moz-extension://',
        ]

    return value
