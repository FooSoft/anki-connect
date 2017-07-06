FROM txgio/anki

RUN mkdir -p /home/anki-user/Documents/Anki/addons

COPY AnkiConnect.py /home/anki-user/Documents/Anki/addons

# Required if you want to access it from another IP address.
# RUN sed -i 's/127.0.0.1/0.0.0.0/' /home/anki-user/Documents/Anki/addons/AnkiConnect.py

COPY tests/prefs.db /home/anki-user/Documents/Anki/prefs.db

CMD /bin/bash -c "(/usr/bin/ibus-daemon -xd; /usr/bin/anki;)"