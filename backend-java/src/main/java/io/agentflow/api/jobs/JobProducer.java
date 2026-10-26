package io.agentflow.api.jobs;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentflow.api.config.AgentflowProperties;
import io.micrometer.tracing.Span;
import io.micrometer.tracing.Tracer;
import io.micrometer.tracing.propagation.Propagator;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * Pushes run jobs onto the broker that the Python worker consumes.
 *
 * <p>The wire format selected by {@code agentflow.jobs.impl} must match the
 * Python worker's configuration:
 *
 * <ul>
 *   <li>{@code streams} (default) -> {@code XADD <queue-key> *
 *       payload=<json>}. The worker reads with {@code XREADGROUP} inside a
 *       consumer group and explicitly {@code XACK}s after the run terminates,
 *       so a worker crash mid-execute lets another consumer reclaim the job
 *       via {@code XAUTOCLAIM}.</li>
 *   <li>{@code list} -> legacy {@code LPUSH} / {@code BRPOP}. At-most-once;
 *       kept for rollback only.</li>
 *   <li>{@code temporal} -> start or signal a Temporal workflow keyed by
 *       {@code run_id}; the Python worker executes activities from the
 *       shared task queue and resumes from checkpoints after a crash.</li>
 * </ul>
 *
 * <p>The JSON payload itself is identical across both modes: a single
 * {@link RunJob} record serialised in snake_case, decoded by Python's
 * {@code RunJob.from_json}.
 */
@Component
public class JobProducer {

    static final String STREAM_PAYLOAD_FIELD = "payload";

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;
    private final AgentflowProperties props;
    private final Tracer tracer;
    private final Propagator propagator;
    private final TemporalWorkflowClient temporal;

    public JobProducer(
            StringRedisTemplate redis,
            ObjectMapper mapper,
            AgentflowProperties props,
            Tracer tracer,
            Propagator propagator,
            TemporalWorkflowClient temporal) {
        this.redis = redis;
        this.mapper = mapper;
        this.props = props;
        this.tracer = tracer;
        this.propagator = propagator;
        this.temporal = temporal;
    }

    public void enqueue(String runId, String agentId, String adapter) {
        Map<String, String> traceContext = captureTraceContext();
        RunJob job = new RunJob(runId, agentId, adapter, Instant.now(), traceContext);
        String payload;
        try {
            payload = mapper.writeValueAsString(job);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialise run job", e);
        }

        String impl = props.getJobs().getImpl();
        if ("temporal".equalsIgnoreCase(impl)) {
            temporal.startOrResume(runId, agentId, adapter, traceContext);
            return;
        }
        String key = props.getJobs().getQueueKey();
        if ("list".equalsIgnoreCase(impl)) {
            redis.opsForList().leftPush(key, payload);
            return;
        }
        // Default: Redis Streams. Single-field map keeps the wire format
        // compatible with Python's ``RunJob.from_json`` -- the consumer
        // reads ``fields["payload"]`` and decodes the JSON.
        redis.opsForStream().add(key, Map.of(STREAM_PAYLOAD_FIELD, payload));
    }

    private Map<String, String> captureTraceContext() {
        if (!props.getOtel().isEnabled()) {
            return null;
        }
        Span current = tracer.currentSpan();
        if (current == null) {
            return null;
        }
        Map<String, String> carrier = new HashMap<>();
        propagator.inject(current.context(), carrier, Map::put);
        return carrier.isEmpty() ? null : carrier;
    }
}
