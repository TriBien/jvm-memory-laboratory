# JVM Memory Laboratory

A hands-on laboratory for understanding automatic resource management in the JVM.

## Learning target

You should be able to explain:

1. Why allocation is cheap until allocation rate or live-set size becomes expensive.
2. How references form an object graph.
3. Why GC collects objects based on reachability, not on whether the application still “cares” about them.
4. Why heap size, allocation rate, live-set size, and GC policy interact.
5. Why GC can improve developer productivity while still hurting tail latency.
6. How a cache can become a memory-retention bug.
7. How Spring request processing becomes an allocation stream.

## Prerequisites

- JDK 21+ recommended; JDK 25/26 are suitable.
- Maven 3.9+.
- Optional: `wrk` or another HTTP load generator.
- Optional: Eclipse MAT for heap-dump analysis.

## Build

```bash
mvn clean package
```

Run the non-Spring experiments:

```bash
CP="target/classes:target/lib/*"
java -cp "$CP" com.example.jvmlab.AllocationStorm 10000000 256
java -cp "$CP" com.example.jvmlab.PrimitiveVsObject 1000000
java -cp "$CP" com.example.jvmlab.CacheRetention leak 200 262144
java -cp "$CP" com.example.jvmlab.CacheRetention fixed 200 262144
```

Run the Spring application:

```bash
java -Xms512m -Xmx512m -XX:+UseG1GC \
  -Xlog:gc*,safepoint:file=build/gc-spring.log:time,uptime,level,tags:filecount=3,filesize=20m \
  -jar target/jvm-memory-laboratory-1.0.0.jar
```

Then:

```bash
curl 'http://localhost:8080/work?objects=5000&payloadBytes=256'
curl 'http://localhost:8080/cache?entries=20&payloadBytes=1048576'
curl 'http://localhost:8080/retention'
curl 'http://localhost:8080/actuator/metrics/jvm.memory.used'
```

## Experiment 1 — Allocation storm

Purpose: connect allocation rate to young-generation collection frequency and GC overhead.

G1:

```bash
java -Xms512m -Xmx512m -XX:+UseG1GC \
  -Xlog:gc*,gc+age=trace,safepoint:file=build/allocation-g1.log:time,uptime,pid,level,tags:filecount=5,filesize=100m \
  -cp target/classes \
  com.example.jvmlab.AllocationStorm 20000000 512
```

ZGC:

```bash
java -Xms512m -Xmx512m -XX:+UseZGC \
  -Xlog:gc*,gc+age=trace,safepoint:file=build/allocation-zgc.log:time,uptime,pid,level,tags:filecount=5,filesize=100m \
  -cp target/classes \
  com.example.jvmlab.AllocationStorm 20000000 512
```

Analyze GC log:
```
# analyze 1 gc log
python3 scripts/gc_analyze.py build/allocation-g1.log 

# compare many gc log
python3 scripts/gc_analyze.py build/allocation-zgc.log build/allocation-g1.log 
```

Record wall-clock time, approximate allocation throughput, GC activity, CPU utilization, and (when driven through HTTP) p95/p99 latency.

Do not start with “which collector is faster?” Start with “which workload characteristic changed the cost?”

## Experiment 2 — Object vs primitive memory

Purpose: expose object headers, references, boxing, and alignment.

```bash
java -cp "target/classes:target/lib/*" \
  com.example.jvmlab.PrimitiveVsObject 1000000
```

Qualitative expectation:

- `int[]` stores primitive values inline.
- `Integer[]` stores references, while each `Integer` object has its own object representation.
- Collection/object-heavy representations add structure beyond payload values.

Exact sizes are VM-dependent. JOL measures the running VM rather than assuming a universal layout.

## Experiment 3 — Cache-induced retention

Leak mode:

```bash
java -Xms256m -Xmx256m -XX:+UseG1GC \
  -cp "target/classes:target/lib/*" \
  com.example.jvmlab.CacheRetention leak 100 1048576
```

Fixed mode:

```bash
java -Xms256m -Xmx256m -XX:+UseG1GC \
  -cp "target/classes:target/lib/*" \
  com.example.jvmlab.CacheRetention fixed 100 1048576
```

Inspect a running process:
``` 
ps aux | grep java 
```

```bash
jcmd <pid> GC.class_histogram > build/histo.txt
jcmd <pid> GC.heap_dump build/cache-retention.hprof
```

Use Eclipse MAT and ask:

> What GC root keeps the supposedly obsolete `byte[]` objects alive?

The intended diagnosis is equivalent to:

`GC root -> static field -> cache map -> entry -> byte[]`

+ Import heap dump build/cache-retention.hprof in Eclipse MAT
+ Open Dominator tree
+ Right click on biggest objects -> Path to GC root -> Exclude soft/weaak/phantom references => find the strong reference object


## Experiment 4 — GC tuning

Baseline G1:

```bash
java -Xms512m -Xmx512m -XX:+UseG1GC \
  -Xlog:gc*,gc+age=trace,safepoint:file=build/g1-baseline.log:time,uptime,pid,level,tags:filecount=5,filesize=100m \
  -cp "target/classes:target/lib/*" \
  com.example.jvmlab.AllocationStorm 20000000 512 \
&& python3 scripts/gc_analyze.py build/g1-baseline.log
```

Tighter pause goal 10ms:

```bash
java -Xms512m -Xmx512m -XX:+UseG1GC -XX:MaxGCPauseMillis=10 \
  -Xlog:gc*,gc+age=trace,safepoint:file=build/g1-10ms.log:time,uptime,pid,level,tags:filecount=5,filesize=100m \
  -cp "target/classes:target/lib/*" \
  com.example.jvmlab.AllocationStorm 20000000 512 \
&& python3 scripts/gc_analyze.py build/g1-10ms.log
```

Relaxed pause goal:

```bash
java -Xms512m -Xmx512m -XX:+UseG1GC -XX:MaxGCPauseMillis=200 \
  -Xlog:gc*,gc+age=trace,safepoint:file=build/g1-200ms.log:time,uptime,pid,level,tags:filecount=5,filesize=100m \
  -cp "target/classes:target/lib/*" \
  com.example.jvmlab.AllocationStorm 20000000 512 \
&& python3 scripts/gc_analyze.py build/g1-200ms.log
```

The pause target is a hint, not a hard real-time guarantee. Tighter pause goals can trade against throughput.

=> Smaller GC pause time (low latency), higher GC CPU (spend more CPU to GC) -> low throughput (less CPU for main app thread, process less work)


## Production mapping — Spring request allocation

The `/work` endpoint creates per-request objects and arrays plus a request-scoped bean. The `/cache` endpoint contains an intentional process-wide retention bug for diagnosis.

Run a load test:

```bash
wrk -t4 -c64 -d60s 'http://127.0.0.1:8080/work?objects=5000&payloadBytes=256'
wrk -t4 -c64 -d60s 'http://127.0.0.1:8080/work?objects=50000&payloadBytes=256'
```

Observe:

```bash
curl 'http://localhost:8080/actuator/metrics/jvm.memory.used'
curl 'http://localhost:8080/actuator/metrics/jvm.gc.pause'
curl 'http://localhost:8080/actuator/prometheus' | grep '^jvm_'
```

Correlate:

`request rate -> allocation rate -> GC frequency/CPU -> pause behavior -> p95/p99 latency`

Do not assume fewer objects automatically means better latency; measure the end-to-end path.

## Mental model

Think of memory as an object graph, not a bag of bytes.

```text
          GC roots
     /       |       \\
   stack   static   thread/local
     |        |         |
     v        v         v
   Object -> Object -> Object
              |
              v
            byte[]
```

If there is a path from a GC root to an object, the object is reachable.

If no GC root can reach it, it is eligible for reclamation.

“Eligible” does not mean “collected immediately.”

## Acceptance

### Explain why GC improves productivity

Developers can allocate temporary objects without manually freeing every object. The runtime reclaims unreachable objects, removing a large class of ownership and lifetime bookkeeping errors.

### Explain why GC can hurt latency

GC consumes CPU and may stop or otherwise compete with application execution. As allocation rate or live-set size rises, the collector has more work. Tail latency can rise even when average throughput looks acceptable.

### Identify a memory-retention bug

Use the cache experiment and heap dump. The bug is not “GC failed”; it is that the cache still strongly references data that the application no longer needs.

## Suggested lab report

| Field | Observation |
|---|---|
| JVM version | |
| Collector | |
| Xms / Xmx | |
| Workload | |
| Allocation rate | |
| Live set | |
| GC count / pause time | |
| p50 | |
| p95 | |
| p99 | |
| RSS / committed heap | |
| Main retention path | |
| Engineering conclusion | |
