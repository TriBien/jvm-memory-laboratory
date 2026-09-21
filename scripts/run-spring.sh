#!/usr/bin/env bash
set -euo pipefail
mkdir -p build
java -Xms512m -Xmx512m -XX:+UseG1GC \
  -Xlog:gc*,safepoint:file=build/spring-gc.log:time,uptime,level,tags:filecount=3,filesize=20m \
  -jar target/jvm-memory-laboratory-1.0.0.jar
