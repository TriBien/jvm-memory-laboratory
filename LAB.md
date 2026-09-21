# JVM Memory Laboratory — Deep-Dive Guide

## 0. Central question

The JVM makes memory reclamation automatic. It does not make object lifetime automatic in the business sense.

The key question is:

> What determines the lifetime of an object?

The most useful answer is:

> Reachability determines eligibility for collection; workload and GC policy determine when reclamation work happens.

---

## 1. Heap and object graph

```text
                           +-----------------+
                           |    GC roots     |
                           |-----------------|
                           | live thread     |
                           | static field    |
                           | runtime handle  |
                           +--------+--------+
                                    |
                                    | reference
                                    v
                         +----------------------+
                         |      Object A        |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |      Object B        |
                         +----------+-----------+
                                    |
                                    v
                               +---------+
                               |  byte[]  |
                               +---------+
```

Important distinction:

`not needed anymore != unreachable`

A cache bug is therefore a reachability/ownership bug.

---

## 2. Allocation

For many short-lived objects, HotSpot allocation can be highly optimized. But allocation is not free.

At least four costs matter:

1. memory must be reserved and initialized;
2. headers, references, and alignment consume space;
3. more garbage creates more reclamation work;
4. survivors may need additional tracking/copying/marking.

The lab increases allocation rate while keeping computation intentionally boring.

---

## 3. Experiment A — Allocation storm

### Hypothesis

Increasing allocation rate increases GC activity and may increase CPU time even when most allocated objects die young.

### Procedure

Run the same workload with a fixed heap under G1 and ZGC. Keep hardware and JVM build constant.

### Observe

- collection frequency
- pause duration
- concurrent GC work if visible
- heap occupancy before/after collections
- wall-clock duration
- CPU utilization

### Reasoning chain

```text
high QPS
   |
   v
more objects/request
   |
   v
more bytes allocated/second
   |
   v
more reclamation work
   |
   +----> CPU competition
   +----> pause/concurrency effects
   |
   v
latency / throughput impact
```

---

## 4. Experiment B — Primitive vs object representation

### Hypothesis

For the same logical values, object-heavy representations consume more memory because values may be distributed across object headers, references, alignment gaps, and separate objects.

Compare:

```text
int[]       -> contiguous primitive storage
Integer[]   -> reference array + many Integer objects
```

Use JOL to inspect the VM's actual object layout.

### Questions

1. What is the size of the array object?
2. What is the size of one `Integer` object on this VM?
3. What is the graph footprint of the whole structure?
4. How does locality differ?

### Engineering lesson

A data representation is also a choice about:

- footprint
- allocation pressure
- cache locality
- GC workload

---

## 5. Experiment C — Cache-induced retention

### Hypothesis

An unbounded cache can turn ordinary allocation into long-lived retention.

The leaky graph looks like:

```text
static CACHE
    |
    v
HashMap table
    |
    v
Map.Entry
    |
    v
byte[]
```

The array may be useless from a business perspective while still being strongly reachable.

### Procedure

1. Start leak mode.
2. Add hundreds of entries.
3. Allow several GCs.
4. Observe that retained usage remains high.
5. Take a heap dump.
6. Open it in Eclipse MAT.
7. Inspect dominators and paths to GC roots.
8. Identify the static field owning the cache.
9. Compare bounded mode.

### Diagnosis

The fix is to change ownership/lifetime, not merely to increase GC effort.

```text
unbounded strong ownership
        |
        v
unbounded retention

bounded ownership
        |
        v
bounded retention
```

Weak references can be appropriate for specific reference/canonicalization patterns, but they are not a generic substitute for cache policy.

---

## 6. Experiment D — GC tuning

Treat tuning as a constrained optimization problem.

Let:

- `A` = allocation rate
- `L` = live-set size
- `H` = heap capacity
- `C` = collector CPU/work
- `P99` = tail latency

A useful qualitative model is:

```text
higher A  -> more garbage production -> more GC work
higher L  -> more live data to retain/scan/move -> more GC work
larger H  -> more room between collections, but larger footprint
collector policy -> different CPU/pause/throughput trade-offs
```

Compare G1 with different pause goals without changing application logic.

### Key constraint

`-XX:MaxGCPauseMillis` is a goal/hint, not a guaranteed real-time bound.

---

## 7. Experiment E — Spring request allocation

A web request is more than business logic.

```text
HTTP request
   |
   +--> container/framework objects
   |
   +--> mapping/dispatch
   |
   +--> controller/service allocations
   |
   +--> serialization/deserialization
   |
   +--> logging/metrics/tracing
   |
   +--> response objects
   |
   v
allocation stream
```

The useful production quantity is:

`allocation bytes/request × requests/second = allocation bytes/second`

Measure it alongside GC and latency.

---

## 8. Acceptance challenge

### Challenge A

Explain in one paragraph why GC is a productivity feature.

### Challenge B

Explain in one paragraph why the same feature can hurt p99 latency.

### Challenge C

Given:

```text
static Map<String, byte[]> CACHE
```

and heap growth after each request batch, identify the retention path.

### Challenge D

Suppose you observe:

- flat live-set size
- high allocation rate
- frequent young collections
- acceptable heap after GC
- rising p99

First hypothesis: allocation/GC CPU and pause interaction, before declaring a memory leak.

### Challenge E

Suppose you observe:

- heap steadily rising
- full collections reclaim very little
- one application class dominates retained heap
- a static map is present in the root path

First hypothesis: retention bug caused by unintended strong ownership.

---

## 9. Production decision tree

```text
Latency degraded?
      |
      +-- heap after GC high?
      |        |
      |        +-- yes --> retention/live-set problem
      |        |
      |        +-- no --> continue
      |
      +-- allocation rate high?
      |        |
      |        +-- yes --> allocation/GC pressure
      |        |
      |        +-- no --> inspect CPU, locks, I/O, safepoints
      |
      +-- full GC frequent?
               |
               +-- yes --> inspect old-gen pressure / humongous objects / retention
```

This is a diagnostic heuristic, not a law.

---

## 10. Final mental model

Separate these questions:

1. How many bytes do we allocate?
2. How long do objects survive?
3. How many bytes remain live?
4. How much CPU does GC consume?
5. What latency does the application experience?

Many JVM incidents become much easier once these are measured independently.
