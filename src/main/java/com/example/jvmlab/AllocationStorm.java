package com.example.jvmlab;

public final class AllocationStorm {
    private AllocationStorm() {}

    private static final class Payload {
        private final byte[] bytes;
        private final long sequence;
        private Payload(int size, long sequence) {
            this.bytes = new byte[size];
            this.sequence = sequence;
        }
        private long checksum() {
            return bytes.length * 31L + sequence;
        }
    }

    public static void main(String[] args) {
        long objects = args.length > 0 ? Long.parseLong(args[0]) : 10_000_000L;
        int payloadBytes = args.length > 1 ? Integer.parseInt(args[1]) : 256;
        if (objects < 1 || payloadBytes < 1) {
            throw new IllegalArgumentException("objects and payloadBytes must be positive");
        }

        int batchSize = 10_000;
        Payload[] batch = new Payload[batchSize];
        long checksum = 0;
        long start = System.nanoTime();
        long allocatedApprox = 0;

        for (long base = 0; base < objects; base += batchSize) {
            int size = (int) Math.min(batchSize, objects - base);
            for (int i = 0; i < size; i++) {
                Payload p = new Payload(payloadBytes, base + i);
                batch[i] = p;
                checksum += p.checksum();
            }
            for (int i = size; i < batchSize; i++) {
                batch[i] = null;
            }
            allocatedApprox += (long) size * payloadBytes;
        }

        long elapsedNanos = System.nanoTime() - start;
        double seconds = elapsedNanos / 1_000_000_000.0;
        double objectsPerSecond = objects / seconds;
        double allocatedMiBPerSecond = (allocatedApprox / 1024.0 / 1024.0) / seconds;

        System.out.printf("""
                Allocation storm complete
                  objects              : %,d
                  payload bytes/object : %,d
                  approximate payload  : %.2f GiB
                  elapsed              : %.3f s
                  objects/s            : %,.0f
                  payload MiB/s        : %,.1f
                  checksum             : %d
                """,
                objects,
                payloadBytes,
                allocatedApprox / 1024.0 / 1024.0 / 1024.0,
                seconds,
                objectsPerSecond,
                allocatedMiBPerSecond,
                checksum
        );
    }
}
