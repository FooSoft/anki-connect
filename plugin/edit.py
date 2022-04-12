import aqt
import aqt.editor
from aqt import gui_hooks
from aqt.qt import QDialog, Qt, QKeySequence, QShortcut
from aqt.utils import disable_help_button, restoreGeom, saveGeom, tooltip
from anki.errors import NotFoundError
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.utils import ids2str


# Edit dialog. Like Edit Current, but:
#   * has a Preview button to preview the cards for the note
#   * has Previous/Back buttons to navigate the history of the dialog
#   * has a Browse button to open the history in the Browser
#   * has no bar with the Close button
#
# To register in Anki's dialog system:
# > from .edit import Edit
# > Edit.register_with_anki()
#
# To (re)open (note_id is an integer):
# > Edit.open_dialog_and_show_note_with_id(note_id)


DOMAIN_PREFIX = "foosoft.ankiconnect."


def get_note_by_note_id(note_id):
    return aqt.mw.col.get_note(note_id)

def is_card_suspended(card):
    return card.queue == QUEUE_TYPE_SUSPENDED

def filter_valid_note_ids(note_ids):
    return aqt.mw.col.db.list(
        "select id from notes where id in " + ids2str(note_ids)
    )


##############################################################################


class DecentPreviewer(aqt.browser.previewer.MultiCardPreviewer):
    class Adapter:
        def get_current_card(self): raise NotImplementedError
        def can_select_previous_card(self): raise NotImplementedError
        def can_select_next_card(self): raise NotImplementedError
        def select_previous_card(self): raise NotImplementedError
        def select_next_card(self): raise NotImplementedError

    def __init__(self, adapter: Adapter):
        super().__init__(parent=None, mw=aqt.mw, on_close=lambda: None) # noqa
        self.adapter = adapter
        self.last_card_id = 0

    def card(self):
        return self.adapter.get_current_card()

    def card_changed(self):
        current_card_id = self.adapter.get_current_card().id
        changed = self.last_card_id != current_card_id
        self.last_card_id = current_card_id
        return changed

    # the check if we can select next/previous card is needed because
    # the buttons sometimes get disabled a tad too late
    # and can still be pressed by user.
    # this is likely due to Anki sometimes delaying rendering of cards
    # in order to avoid rendering them too fast?
    def _on_prev_card(self):
        if self.adapter.can_select_previous_card():
            self.adapter.select_previous_card()
            self.render_card()

    def _on_next_card(self):
        if self.adapter.can_select_next_card():
            self.adapter.select_next_card()
            self.render_card()

    def _should_enable_prev(self):
        return self.showing_answer_and_can_show_question() or \
               self.adapter.can_select_previous_card()

    def _should_enable_next(self):
        return self.showing_question_and_can_show_answer() or \
               self.adapter.can_select_next_card()

    def _render_scheduled(self):
        super()._render_scheduled()  # noqa
        self._updateButtons()

    def showing_answer_and_can_show_question(self):
        return self._state == "answer" and not self._show_both_sides

    def showing_question_and_can_show_answer(self):
        return self._state == "question"


class ReadyCardsAdapter(DecentPreviewer.Adapter):
    def __init__(self, cards):
        self.cards = cards
        self.current = 0

    def get_current_card(self):
        return self.cards[self.current]

    def can_select_previous_card(self):
        return self.current > 0

    def can_select_next_card(self):
        return self.current < len(self.cards) - 1

    def select_previous_card(self):
        self.current -= 1

    def select_next_card(self):
        self.current += 1


##############################################################################


# store note ids instead of notes, as note objects don't implement __eq__ etc
class History:
    number_of_notes_to_keep_in_history = 25

    def __init__(self):
        self.note_ids = []

    def append(self, note):
        if note.id in self.note_ids:
            self.note_ids.remove(note.id)
        self.note_ids.append(note.id)
        self.note_ids = self.note_ids[-self.number_of_notes_to_keep_in_history:]

    def has_note_to_left_of(self, note):
        return note.id in self.note_ids and note.id != self.note_ids[0]

    def has_note_to_right_of(self, note):
        return note.id in self.note_ids and note.id != self.note_ids[-1]

    def get_note_to_left_of(self, note):
        note_id = self.note_ids[self.note_ids.index(note.id) - 1]
        return get_note_by_note_id(note_id)

    def get_note_to_right_of(self, note):
        note_id = self.note_ids[self.note_ids.index(note.id) + 1]
        return get_note_by_note_id(note_id)

    def get_last_note(self):            # throws IndexError if history empty
        return get_note_by_note_id(self.note_ids[-1])

    def remove_invalid_notes(self):
        self.note_ids = filter_valid_note_ids(self.note_ids)

history = History()


# see method `find_cards` of `collection.py`
def trigger_search_for_dialog_history_notes(search_context, use_history_order):
    search_context.search = " or ".join(
        f"nid:{note_id}" for note_id in history.note_ids
    )

    if use_history_order:
        search_context.order = f"""case c.nid {
            " ".join(
                f"when {note_id} then {n}"
                for (n, note_id) in enumerate(reversed(history.note_ids))
            )
        } end asc"""


##############################################################################


# noinspection PyAttributeOutsideInit
class Edit(aqt.editcurrent.EditCurrent):
    dialog_geometry_tag = DOMAIN_PREFIX + "edit"
    dialog_registry_tag = DOMAIN_PREFIX + "Edit"
    dialog_search_tag = DOMAIN_PREFIX + "edit.history"

    # depending on whether the dialog already exists, 
    # upon a request to open the dialog via `aqt.dialogs.open()`,
    # the manager will call either the constructor or the `reopen` method
    def __init__(self, note):
        QDialog.__init__(self, None, Qt.WindowType.Window)
        aqt.mw.garbage_collect_on_dialog_finish(self)
        self.form = aqt.forms.editcurrent.Ui_Dialog()
        self.form.setupUi(self)
        self.setWindowTitle("Edit")
        self.setMinimumWidth(250)
        self.setMinimumHeight(400)
        restoreGeom(self, self.dialog_geometry_tag)
        disable_help_button(self)

        self.form.buttonBox.setVisible(False)   # hides the Close button bar
        self.setup_editor_buttons()

        history.remove_invalid_notes()
        history.append(note)

        self.show_note(note)
        self.show()

        gui_hooks.operation_did_execute.append(self.on_operation_did_execute)
        gui_hooks.editor_did_load_note.append(self.editor_did_load_note)

    def reopen(self, note):
        history.append(note)
        self.show_note(note)

    def cleanup_and_close(self):
        gui_hooks.editor_did_load_note.remove(self.editor_did_load_note)
        gui_hooks.operation_did_execute.remove(self.on_operation_did_execute)

        self.editor.cleanup()
        saveGeom(self, self.dialog_geometry_tag)
        aqt.dialogs.markClosed(self.dialog_registry_tag)
        QDialog.reject(self)

    #################################### hooks enabled during dialog lifecycle

    def on_operation_did_execute(self, changes, handler):
        if changes.note_text and handler is not self.editor:
            self.reload_notes_after_user_action_elsewhere()

    # adjusting buttons right after initializing doesn't have any effect;
    # this seems to do the trick
    def editor_did_load_note(self, _editor):
        self.enable_disable_next_and_previous_buttons()

    ###################################################### load & reload notes

    # setting editor.card is required for the "Cards…" button to work properly
    def show_note(self, note):
        self.note = note
        cards = note.cards()

        self.editor.set_note(note)
        self.editor.card = cards[0] if cards else None

        if any(is_card_suspended(card) for card in cards):
            tooltip("Some of the cards associated with this note " 
                    "have been suspended", parent=self)

    def reload_notes_after_user_action_elsewhere(self):
        history.remove_invalid_notes()

        try:
            self.note.load()                    # this also updates the fields
        except NotFoundError:
            try:
                self.note = history.get_last_note()
            except IndexError:
                self.cleanup_and_close()
                return

        self.show_note(self.note)

    ################################################################## actions

    # search two times, one is to select the current note or its cards,
    # and another to show the whole history, while keeping the above selection
    # set sort column to our search tag, which:
    #  * prevents the column sort indicator from being shown
    #  * serves as a hint for us to show notes or cards in history order
    #    (user can then click on any of the column names
    #    to show history cards in the order of their choosing)
    def show_browser(self, *_):
        def search_input_select_all(hook_browser, *_):
            hook_browser.form.searchEdit.lineEdit().selectAll()
            gui_hooks.browser_did_change_row.remove(search_input_select_all)
        gui_hooks.browser_did_change_row.append(search_input_select_all)

        browser = aqt.dialogs.open("Browser", aqt.mw)
        browser.table._state.sort_column = self.dialog_search_tag  # noqa
        browser.table._set_sort_indicator()  # noqa

        browser.search_for(f"nid:{self.note.id}")
        browser.table.select_all()
        browser.search_for(self.dialog_search_tag)

    def show_preview(self, *_):
        if cards := self.note.cards():
            previewer = DecentPreviewer(ReadyCardsAdapter(cards))
            previewer.open()
            return previewer
        else:
            tooltip("No cards found", parent=self)
            return None

    def show_previous(self, *_):
        if history.has_note_to_left_of(self.note):
            self.show_note(history.get_note_to_left_of(self.note))

    def show_next(self, *_):
        if history.has_note_to_right_of(self.note):
            self.show_note(history.get_note_to_right_of(self.note))

    ################################################## button and hotkey setup

    def setup_editor_buttons(self):
        gui_hooks.editor_did_init.append(self.add_preview_button)
        gui_hooks.editor_did_init_buttons.append(self.add_right_hand_side_buttons)

        self.editor = aqt.editor.Editor(aqt.mw, self.form.fieldsArea, self)

        gui_hooks.editor_did_init_buttons.remove(self.add_right_hand_side_buttons)
        gui_hooks.editor_did_init.remove(self.add_preview_button)

    # taken from `setupEditor` of browser.py
    # PreviewButton calls pycmd `preview`, which is hardcoded.
    # copying _links is needed so that opening Anki's browser does not
    # screw them up as they are apparently shared between instances?!
    def add_preview_button(self, editor):
        QShortcut(QKeySequence("Ctrl+Shift+P"), self, self.show_preview)

        editor._links = editor._links.copy()
        editor._links["preview"] = self.show_preview
        editor.web.eval("""
            $editorToolbar.then(({notetypeButtons}) => 
                notetypeButtons.appendButton(
                    {component: editorToolbar.PreviewButton, id: 'preview'}
                )
            );
        """)

    def add_right_hand_side_buttons(self, buttons, editor):
        def add(cmd, function, label, tip, keys):
            button_html = editor.addButton(
                icon=None, 
                cmd=DOMAIN_PREFIX + cmd, 
                id=DOMAIN_PREFIX + cmd,
                func=function, 
                label=f"&nbsp;&nbsp;{label}&nbsp;&nbsp;",
                tip=f"{tip} ({keys})",
                keys=keys,
            )

            # adding class `btn` properly styles buttons when disabled
            button_html = button_html.replace('class="', 'class="btn ')
            buttons.append(button_html)

        add("browse", self.show_browser, "Browse", "Browse", "Ctrl+F")
        add("previous", self.show_previous, "&lt;", "Previous", "Alt+Left")
        add("next", self.show_next, "&gt;", "Next", "Alt+Right")

    def enable_disable_next_and_previous_buttons(self):
        def to_js(boolean):
            return "true" if boolean else "false"

        disable_previous = to_js(not(history.has_note_to_left_of(self.note)))
        disable_next = to_js(not(history.has_note_to_right_of(self.note)))

        self.editor.web.eval(f"""
            $editorToolbar.then(({{ toolbar }}) => {{
                setTimeout(function() {{
                    document.getElementById("{DOMAIN_PREFIX}previous")
                            .disabled = {disable_previous};
                    document.getElementById("{DOMAIN_PREFIX}next")
                            .disabled = {disable_next};
                }}, 1);
            }});
        """)

    ##########################################################################

    @classmethod
    def browser_will_search(cls, search_context):
        if search_context.search == cls.dialog_search_tag:
            trigger_search_for_dialog_history_notes(
                search_context=search_context,
                use_history_order=cls.dialog_search_tag ==
                        search_context.browser.table._state.sort_column  # noqa
            )

    @classmethod
    def register_with_anki(cls):
        if cls.dialog_registry_tag not in aqt.dialogs._dialogs:  # noqa
            aqt.dialogs.register_dialog(cls.dialog_registry_tag, cls)
            gui_hooks.browser_will_search.append(cls.browser_will_search)

    @classmethod
    def open_dialog_and_show_note_with_id(cls, note_id):    # raises NotFoundError
        note = get_note_by_note_id(note_id)
        return aqt.dialogs.open(cls.dialog_registry_tag, note)
