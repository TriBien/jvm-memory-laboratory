package com.example.jvmlab;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AllocationController {
    private final RequestContext requestContext;

    // Intentional process-wide retention bug: no eviction/expiration.
    private static final Map<String, byte[]> LEAKY_CACHE = new LinkedHashMap<>();

    public AllocationController(RequestContext requestContext) {
        this.requestContext = requestContext;
    }

    @GetMapping("/work")
    public Map<String, Object> work(
            @RequestParam(defaultValue = "5000") int objects,
            @RequestParam(defaultValue = "256") int payloadBytes) {

        if (objects < 1 || objects > 1_000_000) {
            throw new IllegalArgumentException("objects out of range");
        }
        if (payloadBytes < 1 || payloadBytes > 1_000_000) {
            throw new IllegalArgumentException("payloadBytes out of range");
        }

        long checksum = 0;
        for (int i = 0; i < objects; i++) {
            RequestPayload payload = new RequestPayload(new byte[payloadBytes], i);
            checksum += payload.checksum();
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("requestId", requestContext.requestId());
        response.put("objects", objects);
        response.put("payloadBytes", payloadBytes);
        response.put("checksum", checksum);
        return response;
    }

    @GetMapping("/cache")
    public Map<String, Object> cache(
            @RequestParam(defaultValue = "10") int entries,
            @RequestParam(defaultValue = "1048576") int payloadBytes) {

        if (entries < 1 || entries > 1_000) {
            throw new IllegalArgumentException("entries out of range");
        }
        if (payloadBytes < 1 || payloadBytes > 10_000_000) {
            throw new IllegalArgumentException("payloadBytes out of range");
        }

        for (int i = 0; i < entries; i++) {
            LEAKY_CACHE.put(requestContext.requestId() + "-" + i, new byte[payloadBytes]);
        }

        return Map.of(
                "cacheEntries", LEAKY_CACHE.size(),
                "retainedMiBApprox", retainedBytes() / 1024.0 / 1024.0
        );
    }

    @GetMapping("/retention")
    public Map<String, Object> retention() {
        return Map.of(
                "entries", LEAKY_CACHE.size(),
                "retainedMiBApprox", retainedBytes() / 1024.0 / 1024.0
        );
    }

    private static long retainedBytes() {
        return LEAKY_CACHE.values().stream().mapToLong(v -> v.length).sum();
    }

    private record RequestPayload(byte[] bytes, int sequence) {
        long checksum() {
            return bytes.length * 31L + sequence;
        }
    }
}
