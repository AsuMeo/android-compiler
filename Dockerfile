FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android-sdk
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${PATH}:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools"

RUN apt-get update && apt-get install -y     openjdk-17-jdk wget unzip python3 python3-pip     && rm -rf /var/lib/apt/lists/*

# Android SDK
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools &&     wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O /tmp/cmdline-tools.zip &&     unzip -q /tmp/cmdline-tools.zip -d ${ANDROID_HOME}/cmdline-tools &&     mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest &&     rm /tmp/cmdline-tools.zip

RUN yes | sdkmanager --licenses &&     sdkmanager "platform-tools" "build-tools;34.0.0" "platforms;android-34"

WORKDIR /app

RUN pip3 install --no-cache-dir flask flask-cors gunicorn

COPY app.py /app/

EXPOSE 10000

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:10000", "app:app"]
