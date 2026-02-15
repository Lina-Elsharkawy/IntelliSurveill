#!/bin/sh
/usr/bin/mc config host add myminio http://minio:9000 minioadmin minioadmin123;
/usr/bin/mc mb -p myminio/evidence;
/usr/bin/mc anonymous set download myminio/evidence;
exit 0
