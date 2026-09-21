package com.example.jvmlab;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

public final class CacheRetention {
    private CacheRetention() {}

    // Intentional retention bug for the lab.
    private static final Map<String, byte[]> UNBOUNDED_CACHE = new LinkedHashMap<>();

    private static final int MAX_ENTRIES = 32;
    private static final Map<String, byte[]> BOUNDED_CACHE =
            new LinkedHashMap<>(MAX_ENTRIES, 0.75f, true) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, byte[]> eldest) {
                    return size() > MAX_ENTRIES;
                }
            };

    public static void main(String[] args) throws Exception {
        String mode = args.length > 0 ? args[0] : "leak";
        int entries = args.length > 1 ? Integer.parseInt(args[1]) : 200;
        int bytesPerEntry = args.length > 2 ? Integer.parseInt(args[2]) : 256 * 1024;

        if (!mode.equals("leak") && !mode.equals("fixed")) {
            throw new IllegalArgumentException("mode must be leak or fixed");
        }

        Map<String, byte[]> cache = mode.equals("leak") ? UNBOUNDED_CACHE : BOUNDED_CACHE;

        for (int i = 0; i < entries; i++) {
            cache.put(mode + "-" + i, new byte[bytesPerEntry]);
            if (i % 20 == 0) {
                System.out.printf("entry=%d cacheSize=%d%n", i, cache.size());
                TimeUnit.MILLISECONDS.sleep(20);
            }
        }

        System.out.println("Calling System.gc() for the experiment.");
        System.gc();
        Thread.sleep(1_000);

        System.out.printf(
                "mode=%s cacheSize=%d retainedPayloadApprox=%.2f MiB%n",
                mode,
                cache.size(),
                cache.size() * bytesPerEntry / 1024.0 / 1024.0
        );

        System.out.println("Keep this process alive for heap inspection.");
        Thread.sleep(TimeUnit.MINUTES.toMillis(10));
    }
}
