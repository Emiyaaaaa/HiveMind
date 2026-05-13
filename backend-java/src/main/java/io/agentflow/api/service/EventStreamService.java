package io.agentflow.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.dto.RunEvent;
import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Bridges the worker's Redis pub/sub stream to per-run SSE emitters. Each
 * subscriber gets its own {@link MessageListener} on the channel; lifecycle
 * is tied to the {@link SseEmitter} (completion/timeout/error all remove
 * the listener).
 */
@Service
public class EventStreamService {

    private static final Logger log = LoggerFactory.getLogger(EventStreamService.class);
    private static final Set<String> TERMINAL_TYPES =
            Set.of("run.completed", "run.failed", "run.cancelled");

    private final RedisMessageListenerContainer listenerContainer;
    private final ObjectMapper mapper;
    private final AgentflowProperties props;
    private final ScheduledExecutorService heartbeatExecutor =
            Executors.newScheduledThreadPool(
                    2, r -> {
                        Thread t = new Thread(r, "sse-heartbeat");
                        t.setDaemon(true);
                        return t;
                    });
    private final Map<SseEmitter, MessageListener> active = new ConcurrentHashMap<>();

    public EventStreamService(
            RedisMessageListenerContainer listenerContainer,
            ObjectMapper mapper,
            AgentflowProperties props) {
        this.listenerContainer = listenerContainer;
        this.mapper = mapper;
        this.props = props;
    }

    public SseEmitter subscribe(String runId) {
        SseEmitter emitter = new SseEmitter(0L);
        ChannelTopic topic = new ChannelTopic(props.getEvents().getChannelPrefix() + runId);

        MessageListener listener = (message, pattern) -> {
            try {
                String body = new String(message.getBody());
                RunEvent event = mapper.readValue(body, RunEvent.class);
                emitter.send(
                        SseEmitter.event()
                                .name(event.type())
                                .data(body));
                if (TERMINAL_TYPES.contains(event.type())) {
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
            MessageListener removed = active.remove(emitter);
            if (removed != null) {
                listenerContainer.removeMessageListener(removed, topic);
            }
        };
        emitter.onCompletion(cleanup);
        emitter.onTimeout(cleanup);
        emitter.onError(t -> cleanup.run());

        return emitter;
    }
}
