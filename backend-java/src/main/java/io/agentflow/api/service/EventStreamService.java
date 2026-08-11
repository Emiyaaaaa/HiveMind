package io.agentflow.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.dto.RunEvent;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Bridges the worker's Redis pub/sub stream to per-run SSE emitters. Each
 * subscriber gets its own {@link org.springframework.data.redis.connection.MessageListener}
 * on the channel; lifecycle is tied to the {@link SseEmitter}.
 *
 * <p>Events are also persisted in a Redis Stream per run so clients can
 * reconnect with {@code Last-Event-ID} and receive any missed frames.
 */
@Service
public class EventStreamService {

    private static final Logger log = LoggerFactory.getLogger(EventStreamService.class);
    private static final Set<String> TERMINAL_TYPES =
            Set.of("run.completed", "run.failed", "run.cancelled");

    private final RedisMessageListenerContainer listenerContainer;
    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;
    private final AgentflowProperties props;
    private final ScheduledExecutorService heartbeatExecutor =
            Executors.newScheduledThreadPool(
                    2, r -> {
                        Thread t = new Thread(r, "sse-heartbeat");
                        t.setDaemon(true);
                        return t;
                    });
    private final Map<SseEmitter, org.springframework.data.redis.connection.MessageListener> active =
            new ConcurrentHashMap<>();

    public EventStreamService(
            RedisMessageListenerContainer listenerContainer,
            StringRedisTemplate redis,
            ObjectMapper mapper,
            AgentflowProperties props) {
        this.listenerContainer = listenerContainer;
        this.redis = redis;
        this.mapper = mapper;
        this.props = props;
    }

    @PreDestroy
    void shutdown() {
        heartbeatExecutor.shutdownNow();
    }

    public SseEmitter subscribe(String runId) {
        return subscribe(runId, null);
    }

    public SseEmitter subscribe(String runId, String afterEventId) {
        SseEmitter emitter = new SseEmitter(0L);
        ChannelTopic topic = new ChannelTopic(props.getEvents().getChannelPrefix() + runId);
        String streamKey = streamKey(runId);
        String after = normalizeEventId(afterEventId);
        AtomicReference<String> lastSentId = new AtomicReference<>(after);
        // Serializes catch-up replay and live pub/sub delivery for one emitter.
        final Object deliveryLock = new Object();

        try {
            synchronized (deliveryLock) {
                if (!replay(emitter, streamKey, after, lastSentId)) {
                    return emitter;
                }
            }
        } catch (Exception e) {
            log.warn("Failed to replay SSE events for run {}", runId, e);
            emitter.completeWithError(e);
            return emitter;
        }

        org.springframework.data.redis.connection.MessageListener listener = (message, pattern) -> {
            synchronized (deliveryLock) {
                try {
                    DeliveredEvent delivered =
                            parseEnvelope(new String(message.getBody(), StandardCharsets.UTF_8));
                    if (shouldSkip(delivered.eventId(), lastSentId.get())) {
                        return;
                    }
                    send(emitter, delivered);
                    if (delivered.eventId() != null) {
                        lastSentId.set(delivered.eventId());
                    }
                    if (TERMINAL_TYPES.contains(delivered.event().type())) {
                        emitter.complete();
                    }
                } catch (IllegalStateException ignored) {
                    // emitter already completed
                } catch (IOException e) {
                    log.debug("SSE send failed for run {}: {}", runId, e.toString());
                    emitter.completeWithError(e);
                } catch (Exception e) {
                    log.warn("Failed to deliver SSE message for run {}", runId, e);
                }
            }
        };

        listenerContainer.addMessageListener(listener, topic);
        active.put(emitter, listener);

        long heartbeatSeconds = Math.max(1, props.getEvents().getSseHeartbeatSeconds());
        ScheduledFuture<?> heartbeat = heartbeatExecutor.scheduleAtFixedRate(
                () -> {
                    try {
                        emitter.send(SseEmitter.event().name("ping").data("{}"));
                    } catch (Exception ignored) {
                        // emitter likely closed
                    }
                },
                heartbeatSeconds,
                heartbeatSeconds,
                TimeUnit.SECONDS);

        Runnable cleanup = () -> {
            heartbeat.cancel(true);
            org.springframework.data.redis.connection.MessageListener removed = active.remove(emitter);
            if (removed != null) {
                listenerContainer.removeMessageListener(removed, topic);
            }
        };
        // Register before catch-up so complete() during replay still cleans up.
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(t -> cleanup.run());

        try {
            synchronized (deliveryLock) {
                if (!replay(emitter, streamKey, lastSentId.get(), lastSentId)) {
                    return emitter;
                }
            }
        } catch (Exception e) {
            log.warn("Failed catch-up replay for run {}", runId, e);
            emitter.completeWithError(e);
            return emitter;
        }

        try {
            emitter.send(SseEmitter.event().name("ping").data("{}"));
        } catch (Exception ignored) {
            // client may have disconnected before subscribe returns
        }

        return emitter;
    }

    private String streamKey(String runId) {
        return props.getEvents().getChannelPrefix() + runId + props.getEvents().getStreamSuffix();
    }

    /** @return {@code false} when a terminal event was replayed. */
    private boolean replay(
            SseEmitter emitter,
            String streamKey,
            String afterEventId,
            AtomicReference<String> lastSentId)
            throws IOException {
        Range<String> range =
                afterEventId == null || afterEventId.isBlank()
                        ? Range.unbounded()
                        : Range.of(Range.Bound.exclusive(afterEventId), Range.Bound.unbounded());

        List<MapRecord<String, Object, Object>> records =
                redis.opsForStream().range(streamKey, range);
        if (records == null) {
            return true;
        }

        for (MapRecord<String, Object, Object> record : records) {
            Object payload = record.getValue().get("payload");
            if (payload == null) {
                continue;
            }
            RunEvent event = mapper.readValue(payload.toString(), RunEvent.class);
            String eventId = record.getId().getValue();
            if (shouldSkip(eventId, lastSentId.get())) {
                continue;
            }
            send(emitter, new DeliveredEvent(eventId, event));
            lastSentId.set(eventId);
            if (TERMINAL_TYPES.contains(event.type())) {
                emitter.complete();
                return false;
            }
        }
        return true;
    }

    private void send(SseEmitter emitter, DeliveredEvent delivered) throws IOException {
        String body = mapper.writeValueAsString(delivered.event());
        SseEmitter.SseEventBuilder builder =
                SseEmitter.event().name(delivered.event().type()).data(body);
        if (delivered.eventId() != null) {
            builder.id(delivered.eventId());
        }
        emitter.send(builder);
    }

    private DeliveredEvent parseEnvelope(String body) throws IOException {
        JsonNode root = mapper.readTree(body);
        if (root.has("event")) {
            String eventId = normalizeEventId(root.path("id").asText(null));
            RunEvent event = mapper.treeToValue(root.get("event"), RunEvent.class);
            return new DeliveredEvent(eventId, event);
        }
        return new DeliveredEvent(null, mapper.readValue(body, RunEvent.class));
    }

    /** Ephemeral frames (null/blank id) always pass; persisted ids are deduped. */
    static boolean shouldSkip(String candidateId, String lastId) {
        if (candidateId == null || lastId == null) {
            return false;
        }
        return !isAfter(candidateId, lastId);
    }

    static String normalizeEventId(String raw) {
        if (raw == null) {
            return null;
        }
        String trimmed = raw.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    static boolean isAfter(String candidate, String lastId) {
        if (candidate.contains("-") || lastId.contains("-")) {
            return compareStreamId(candidate, lastId) > 0;
        }
        try {
            return Long.parseLong(candidate) > Long.parseLong(lastId);
        } catch (NumberFormatException ex) {
            return candidate.compareTo(lastId) > 0;
        }
    }

    private static int compareStreamId(String left, String right) {
        String[] leftParts = left.split("-", 2);
        String[] rightParts = right.split("-", 2);
        if (leftParts.length == 2 && rightParts.length == 2) {
            try {
                int ms = Long.compare(Long.parseLong(leftParts[0]), Long.parseLong(rightParts[0]));
                if (ms != 0) {
                    return ms;
                }
                return Long.compare(Long.parseLong(leftParts[1]), Long.parseLong(rightParts[1]));
            } catch (NumberFormatException ignored) {
                // fall through
            }
        }
        return left.compareTo(right);
    }

    private record DeliveredEvent(String eventId, RunEvent event) {}
}
