FROM flink:2.1.1-scala_2.12-java21

# Install Python 3 and pip
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev && \
    ln -s /usr/bin/python3 /usr/bin/python

# Install PyFlink and other dependencies
COPY requirements.txt /opt/flink/requirements.txt
RUN pip3 install -r /opt/flink/requirements.txt

# Copy the Flink job
COPY frequency_anomaly_job.py /opt/flink/frequency_anomaly_job.py

WORKDIR /opt/flink
