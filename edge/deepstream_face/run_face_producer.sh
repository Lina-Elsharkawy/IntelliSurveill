#!/usr/bin/env bash
set -euo pipefail

cd /opt/deepstream_face

ENV_FILE="${1:-/opt/deepstream_face/face_producer.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: Config file not found: $ENV_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [ -z "${LAPTOP_IP:-}" ]; then
  echo "ERROR: LAPTOP_IP is missing in $ENV_FILE"
  exit 1
fi

export KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-${LAPTOP_IP}:9092}"
export EVIDENCE_GATEWAY_UPLOAD="${EVIDENCE_GATEWAY_UPLOAD:-http://${LAPTOP_IP}:8010/evidence/upload}"
export LIVE_UDP_HOST="${LIVE_UDP_HOST:-${LAPTOP_IP}}"

echo "============================================================"
echo "Starting IntelliSurveil Face Producer"
echo "Config file:        $ENV_FILE"
echo "Laptop IP:          $LAPTOP_IP"
echo "Kafka bootstrap:    $KAFKA_BOOTSTRAP"
echo "Evidence gateway:   $EVIDENCE_GATEWAY_UPLOAD"
echo "Live UDP target:    ${LIVE_UDP_HOST}:${LIVE_UDP_PORT}"
echo "SCRFD config:       ${SCRFD_CONFIG_OVERRIDE:-default}"
echo "Camera ID:          $CAMERA_ID"
echo "Face infer every:   ${FACE_INFER_EVERY_N:-1} frame(s)"
echo "============================================================"

python3 deepstream_face_recognition_producer.py
