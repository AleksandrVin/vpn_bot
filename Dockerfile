FROM linuxserver/wireguard:1.0.20210914-legacy

RUN \
  echo "**** install python ****" && \
  apk add --no-cache \
    python3 \
    py3-pip

COPY ./requirements.txt /root/app/requirements.txt

RUN \
  echo "**** install python packages ****" && \
  pip3 install --no-cache-dir -r /root/app/requirements.txt

COPY ./root/app/manage-peer /root/app/manage-peer

COPY ./bot.py /root/app/bot.py
COPY ./manage_token.py /root/app/manage_token.py
