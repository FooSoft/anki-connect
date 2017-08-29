FROM txgio/anki:2.1.0beta14

RUN apt-get update && \
    apt-get install -y xvfb

COPY AnkiConnect.py /data/addons21/AnkiConnect.py

COPY tests/docker/2.1.x/prefs21.db /data/prefs21.db

ADD tests/docker/2.1.x/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

CMD ["anki", "-b", "/data"]