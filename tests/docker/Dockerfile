FROM txgio/anki

USER root
RUN apt-get update
RUN apt-get install -y xvfb
USER anki-user

RUN mkdir -p /home/anki-user/Documents/Anki/addons

COPY AnkiConnect.py /home/anki-user/Documents/Anki/addons

ENV ANKICONNECT_BIND_ADDRESS 0.0.0.0

COPY tests/docker/prefs.db /home/anki-user/Documents/Anki/prefs.db

ADD tests/docker/entrypoint.sh /entrypoint.sh

USER root
RUN chmod +x /entrypoint.sh
USER anki-user

ENTRYPOINT ["/entrypoint.sh"]

CMD /bin/bash -c "(/usr/bin/ibus-daemon -xd; /usr/bin/anki;)"