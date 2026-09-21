#!/usr/bin/env bash
set -euo pipefail
mkdir -p build
java -Xms512m -Xmx512m -XX:+UseG1GC -XX:MaxGCPauseMillis=200 \
  -Xlog:gc*,safepoint:file=build/g1-200ms.log:time,uptime,level,tags:filecount=3,filesize=20m \
  -cp target/classes \
  com.example.jvmlab.AllocationStorm 20000000 512
