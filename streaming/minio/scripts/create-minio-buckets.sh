#!/bin/sh
/usr/bin/mc config host add myminio http://minio:9000 minioadmin minioadmin;
/usr/bin/mc mb myminio/airflow;
/usr/bin/mc policy set public myminio/airflow;
exit 0;
