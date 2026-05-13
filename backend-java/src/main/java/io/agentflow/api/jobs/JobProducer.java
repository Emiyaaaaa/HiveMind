package io.agentflow.api.jobs;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentflow.api.config.AgentflowProperties;
import java.time.Instant;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * Pushes run jobs onto the Redis list that the Python worker consumes with
 * {@code BRPOP}. {@code LPUSH} + {@code BRPOP} gives FIFO semantics.
 */
@Component
public class JobProducer {

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;
    private final AgentflowProperties props;

    public JobProducer(StringRedisTemplate redis, ObjectMapper mapper, AgentflowProperties props) {
        this.redis = redis;
        this.mapper = mapper;
        this.props = props;
    }

    public void enqueue(String runId, String agentId, String adapter) {
        RunJob job = new RunJob(runId, agentId, adapter, Instant.now());
        try {
            String payload = mapper.writeValueAsString(job);
            redis.opsForList().leftPush(props.getJobs().getQueueKey(), payload);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialise run job", e);
        }
    }
}
