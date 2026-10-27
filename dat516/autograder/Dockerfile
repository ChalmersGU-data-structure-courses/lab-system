FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pytest==8.3.5 \
    hypothesis==6.131.15 \
    networkx==3.4.2 \
    django==5.2.1 \
    graphviz==0.20.3

COPY data /data
COPY lab1 /lab1
RUN chmod -R a+rX /data /lab1

WORKDIR /submission
CMD ["pytest", "-q", "--tb=short"]

