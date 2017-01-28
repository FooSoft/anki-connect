# AnkiConnect #

The AnkiConnect plugin enables external applications such as [Yomichan for Chrome](https://foosoft.net/projects/yomichan-chrome/) to
communicate with Anki over a remote API. This makes it possible to execute queries against the user's card deck,
automatically create new vocabulary and Kanji flash cards, and more.

## Requirements ##

* [Anki](http://ankisrs.net/)

## Installation ##

AnkiConnect can be downloaded from its [Anki shared addon page](https://ankiweb.net/shared/info/2055492159) or enabled
through the [Yomichan](https://foosoft.net/projects/yomichan) plugin if you have it installed. Once AnkiConnect is installed it is ready
for use; no further configuration is required. Windows users may have to take additional steps to make Windows Firewall
allows AnkiConnect to listen for incoming connections on TCP port 8765.

## Limitations on Mac OS X ##

While it is possible to use this plugin on this operating system, there is a known issue in which it is required that
the Anki application window to be on screen for card creation to work properly. The cause is apparently that Mac OS X
suspends graphical applications running in the background, thus preventing Anki from responding to Yomichan queries.

Until this problem is resolved, users of this Mac OS X will have to keep both the browser window and Anki on-screen.
Sorry for the lameness; I am researching a fix for this issue.

## License ##

GPL
