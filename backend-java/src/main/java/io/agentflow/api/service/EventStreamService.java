package io.agentflow.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.dto.RunEvent;
import java.io.IOException;
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

    public SseEmitter subscribe(String runId) {
        return subscribe(runId, null);
    }

    public SseEmitter subscribe(String runId, String afterEventId) {
        SseEmitter emitter = new SseEmitter(0L);
        ChannelTopic topic = new ChannelTopic(props.getEvents().getChannelPrefix() + runId);
        String streamKey = streamKey(runId);
        AtomicReference<String> lastSentId = new AtomicReference<>(afterEventId);

        try {
            if (!replay(emitter, streamKey, afterEventId, lastSentId)) {
                return emitter;
            }
        } catch (Exception e) {
            log.warn("Failed to replay SSE events for run {}", runId, e);
            emitter.completeWithError(e);
            return emitter;
        }

        org.springframework.data.redis.connection.MessageListener listener = (message, pattern) -> {
            try {
                DeliveredEvent delivered = parseEnvelope(new String(message.getBody()));
                if (delivered.eventId() != null
                        && lastSentId.get() != null
                        && !isAfter(delivered.eventId(), lastSentId.get())) {
                    return;
                }
                if (!send(emitter, delivered)) {
                    return;
                }
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
        };

        listenerContainer.addMessageListener(listener, topic);
        active.put(emitter, listener);

        try {
            replay(emitter, streamKey, lastSentId.get(), lastSentId);
        } catch (Exception e) {
            log.warn("Failed catch-up replay for run {}", runId, e);
        }

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
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(t -> cleanup.run());

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
            DeliveredEvent delivered = new DeliveredEvent(record.getId().getValue(), event);
            if (!send(emitter, delivered)) {
                return false;
            }
            lastSentId.set(delivered.eventId());
            if (TERMINAL_TYPES.contains(event.type())) {
                emitter.complete();
                return false;
            }
        }
        return true;
    }

    private boolean send(SseEmitter emitter, DeliveredEvent delivered) throws IOException {
        String body = mapper.writeValueAsString(delivered.event());
        SseEmitter.SseEventBuilder builder =
                SseEmitter.event().name(delivered.event().type()).data(body);
        if (delivered.eventId() != null) {
            builder.id(delivered.eventId());
        }
        emitter.send(builder);
        return true;
    }

    private DeliveredEvent parseEnvelope(String body) throws IOException {
        JsonNode root = mapper.readTree(body);
        if (root.has("id") && root.has("event")) {
            String eventId = root.get("id").asText();
            RunEvent event = mapper.treeToValue(root.get("event"), RunEvent.class);
            return new DeliveredEvent(eventId, event);
        }
        return new DeliveredEvent(null, mapper.readValue(body, RunEvent.class));
    }

    private static boolean isAfter(String candidate, String lastId) {
        try {
            return Long.parseLong(candidate) > Long.parseLong(lastId);
        } catch (NumberFormatException ex) {
            return candidate.compareTo(lastId) > 0;
        }
    }

    private record DeliveredEvent(String eventId, RunEvent event) {}
}
