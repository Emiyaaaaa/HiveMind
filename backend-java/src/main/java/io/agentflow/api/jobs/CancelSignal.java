package io.agentflow.api.jobs;

import io.agentflow.api.config.AgentflowProperties;
import java.time.Duration;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * Sets a per-run cancellation flag in Redis. The Python worker polls this
 * key (and short-circuits any adapter loop) when it sees the value.
 */
@Component
public class CancelSignal {

    private final StringRedisTemplate redis;
    private final AgentflowProperties props;

    public CancelSignal(StringRedisTemplate redis, AgentflowProperties props) {
        this.redis = redis;
        this.props = props;
    }

    public void requestCancel(String runId) {
        String key = props.getCancel().getKeyPrefix() + runId;
        redis.opsForValue().set(key, "1", Duration.ofSeconds(props.getCancel().getTtlSeconds()));
    }
}
