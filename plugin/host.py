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

import inspect
import PyQt5

from . import web


class ApiHost:
    def __init__(self, origins, key, address, port):
        self.origins = origins
        self.key = key
        self.modules = []
        self.server = web.WebServer(self.handler)
        self.server.bindAndListen(address, port)


    def run(self, interval):
        self.timer = PyQt5.QtCore.QTimer()
        self.timer.timeout.connect(self.server.advance)
        self.timer.start(interval)


    def register(self, module):
        self.modules.append(module)


    def handler(self, call):
        action = call.get('action')
        params = call.get('params', {})

        try:
            for module in self.modules:
                for funcName, funcInstance in inspect.getmembers(module, predicate=inspect.isfunction):
                    if funcName == action and getattr(funcInstance, 'api', False):
                        return {'error': None, 'result': funcInstance(**params)}
            else:
                raise Exception('unsupported action')

        except Exception as e:
            return {'error': str(e), 'result': None}

# if '*' in self.origins:
#     origin = '*'
#     allowed = True
# else:
#     origin = request.headers.get('origin', 'http://127.0.0.1:')
#     for prefix in self.origins:
#         if origin.startswith(prefix):
#             allowed = True
#             break
#
# try:
#     if request.body:
#         call = json.loads(request.body)
#         call['allowed'] = allowed
#         call['origin'] = origin
#         body = json.dumps(self.handler(call))
#     else:
#         body = 'AnkiConnect'
# except Exception as e:
#     body = str(e)

