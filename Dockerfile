FROM linuxserver/wireguard:1.0.20210914-legacy

ENV PYTHONUNBUFFERED=1

RUN \
  echo "**** install python ****" && \
  apk add --no-cache \
    python3 \
    py3-pip

RUN \
  echo "**** install python packages ****" && \
  pip3 install poetry

COPY ./pyproject.toml /root/app/pyproject.toml
COPY ./poetry.lock /root/app/poetry.lock

RUN poetry config virtualenvs.create false
RUN poetry install --no-dev

COPY ./root/app/manage-peer /root/app/manage-peer

COPY ./bot.py /root/app/bot.py
COPY ./manage_token.py /root/app/manage_token.py

CMD ["python3", "/root/app/bot.py"]
