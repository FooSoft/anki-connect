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

from . import web


class ApiHost:
    def __init__(self, origins, key, interval, address, port):
        self.key = key
        self.modules = []

        self.server = web.WebServer(self.handler, origins)
        self.server.bindAndListen(address, port)

        self.timer = QTimer()
        self.timer.timeout.connect(self.advance)
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

            method = None
            for module in self.modules:
                for methodName, methodInstance in inspect.getmembers(module, predicate=inspect.ismethod):
                    if getattr(methodInstance, 'api', False):
                        method = methodInstance
                        break

            if method:
                return {'error': None, 'result': methodInstance(**params)}
            else:
                raise Exception('unsupported action')

        except Exception as e:
            return {'error': str(e), 'result': None}


def api(method):
    setattr(method, 'api', True)
    return decorator
