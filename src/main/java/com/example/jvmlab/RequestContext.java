package com.example.jvmlab;

import java.time.Instant;
import java.util.UUID;

import org.springframework.stereotype.Component;
import org.springframework.web.context.annotation.RequestScope;

@Component
@RequestScope
public class RequestContext {
    private final String requestId = UUID.randomUUID().toString();
    private final Instant startedAt = Instant.now();

    public String requestId() {
        return requestId;
    }

    public Instant startedAt() {
        return startedAt;
    }
}
