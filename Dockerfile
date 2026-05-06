# Use the  Ubuntu 22.04 Image support CUDA 12.1 
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Setting Environment Configuraiton and Suppress interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Istall Python 3.10 And reqiure System package
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# To Run In Python Path
RUN ln -s /usr/bin/python3.10 /usr/bin/python

# Setup Working Directory
WORKDIR /code

# Clone and Install Requirements.txt
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /code/requirements.txt

# Clone Project Source Codes
COPY . /code

# 開放指定Port 5004
EXPOSE 5004

# 使用 ENTRYPOINT 執行啟動腳本
ENTRYPOINT ["/code/entrypoint.sh"]