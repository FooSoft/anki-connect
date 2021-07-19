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

import PyQt5

from . import web


class ApiHost:
    def __init__(self, origins, key, address, port):
        self.key = key
        self.modules = []
        self.server = web.WebServer(self.handler, origins)
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
        allowed = call.get('allowed', False)
        key = call.get('key')

        try:
            if key != self.key and action != 'requestPermission':
                raise Exception('valid api key must be provided')

            for module in self.modules:
                for methodName, methodInstance in inspect.getmembers(module, predicate=inspect.ismethod):
                    if methodName == action and getattr(methodInstance, 'api', False):
                        return {'error': None, 'result': methodInstance(**params)}
            else:
                raise Exception('unsupported action')

        except Exception as e:
            return {'error': str(e), 'result': None}
