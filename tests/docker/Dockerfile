FROM txgio/anki:2.0.45

RUN apt-get update && \
    apt-get install -y xvfb

#COPY AnkiConnect.py /data/addons/AnkiConnect.py

COPY tests/docker/prefs.db /data/prefs.db

ADD tests/docker/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

CMD ["anki", "-b", "/data"]