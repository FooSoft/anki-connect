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

import aqt


def api(method):
    setattr(method, 'api', True)
    return method


def window(self):
    return aqt.mw


def reviewer():
    return window().reviewer


def collection(self):
    return window().col


def decks(self):
    return collection().decks


def scheduler(self):
    return collection().sched


def database(self):
    return collection().db


def media(self):
    return collection().media


def deckNames():
    return decks().allNames()


class EditScope:
    def __enter__(self):
        window().requireReset()

    def __exit__(self):
        window().maybeReset()
