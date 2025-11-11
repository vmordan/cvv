FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

# -------------------------------
# System dependencies
# -------------------------------
RUN apt update && \
    apt install -y \
        software-properties-common \
        build-essential \
        git \
        python3-dev \
        python3-pip \
        python3-setuptools \
        python3-wheel \
        gettext \
        postgresql \
        libpq-dev \
        graphviz \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

# Needed for some Python packages on Ubuntu 20
RUN pip3 install --upgrade pip && \
    pip3 install "setuptools<66.0.0"

# -------------------------------
# Python dependencies
# -------------------------------
RUN pip3 install \
        requests \
        ujson \
        django==4.2 \
        pluggy \
        py \
        attrs \
        six \
        more-itertools \
        ply \
        pytest \
        atomicwrites \
        pycparser \
        psycopg2-binary \
        sympy \
        pytz

# -------------------------------
# Create working directory
# -------------------------------
RUN git clone https://github.com/ispras/cv-visualizer.git /cvv
WORKDIR /cvv
RUN deploys/deployment.sh cvdb

# -------------------------------
# Expose default CVV port
# -------------------------------
EXPOSE 8989

# -------------------------------
# Create an entrypoint
# -------------------------------
COPY deploys/entrypoint.sh /cvv/entrypoint.sh
RUN chmod +x /cvv/entrypoint.sh

ENTRYPOINT ["/cvv/entrypoint.sh"]

