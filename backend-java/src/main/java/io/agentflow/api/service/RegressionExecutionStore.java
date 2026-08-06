package io.agentflow.api.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.Optional;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
public class RegressionExecutionStore {

    private static final String KEY_PREFIX = "agentflow:regression:execution:";
    private static final Duration TTL = Duration.ofDays(30);

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;

    public RegressionExecutionStore(StringRedisTemplate redis, ObjectMapper mapper) {
        this.redis = redis;
        this.mapper = mapper;
    }

    public void save(RegressionExecutionManifest manifest) {
        try {
            redis.opsForValue().set(
                    key(manifest.executionId()), mapper.writeValueAsString(manifest), TTL);
        } catch (JsonProcessingException | RuntimeException ex) {
            throw RegressionExecutionException.unavailable(
                    "Failed to store temporary regression execution manifest", ex);
        }
    }

    public Optional<RegressionExecutionManifest> find(String executionId) {
        try {
            String json = redis.opsForValue().get(key(executionId));
            if (json == null) {
                return Optional.empty();
            }
            return Optional.of(mapper.readValue(json, RegressionExecutionManifest.class));
        } catch (JsonProcessingException | RuntimeException ex) {
            throw RegressionExecutionException.unavailable(
                    "Failed to read temporary regression execution manifest", ex);
        }
    }

    private String key(String executionId) {
        return KEY_PREFIX + executionId;
    }
}
