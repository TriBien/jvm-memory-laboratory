#!/usr/bin/env bash
set -euo pipefail
mkdir -p build
java -Xms512m -Xmx512m -XX:+UseZGC \
  -Xlog:gc*,safepoint:file=build/zgc-baseline.log:time,uptime,level,tags:filecount=3,filesize=20m \
  -cp target/classes \
  com.example.jvmlab.AllocationStorm 20000000 512
