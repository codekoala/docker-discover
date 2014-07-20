FROM codekoala/python
MAINTAINER Josh VanderLinden <codekoala@gmail.com>

RUN pacman -Sy --needed --noconfirm haproxy python-jinja python-etcd
RUN touch /var/run/haproxy.pid

ADD . /app
WORKDIR /app

EXPOSE 1936

CMD ["python", "main.py"]

