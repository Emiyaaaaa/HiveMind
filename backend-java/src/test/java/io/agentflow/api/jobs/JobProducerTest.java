package io.agentflow.api.jobs;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import io.agentflow.api.config.AgentflowProperties;
import io.micrometer.tracing.Tracer;
import io.micrometer.tracing.propagation.Propagator;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

class JobProducerTest {

    private ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.registerModule(new JavaTimeModule());
        mapper.setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
        return mapper;
    }

    private AgentflowProperties props(String impl) {
        AgentflowProperties p = new AgentflowProperties();
        p.getJobs().setImpl(impl);
        p.getJobs().setQueueKey("test:agentflow:jobs:runs");
        return p;
    }

    @Test
    void streamsModeWritesPayloadFieldViaXadd() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("rawtypes")
        StreamOperations stream = mock(StreamOperations.class);
        when(redis.opsForStream()).thenReturn(stream);
        when(stream.add(anyString(), any(Map.class))).thenReturn(RecordId.of("1-0"));

        JobProducer producer = new JobProducer(
                redis, objectMapper(), props("streams"), noopTracer(), noopPropagator());
        producer.enqueue("run-1", "agent-1", "echo");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
        verify(stream).add(eq("test:agentflow:jobs:runs"), bodyCaptor.capture());
        String payload = bodyCaptor.getValue().get(JobProducer.STREAM_PAYLOAD_FIELD);
        assertThat(payload).isNotNull();
        // snake_case keys per docs/api-contract.md.
        assertThat(payload).contains("\"run_id\":\"run-1\"");
        assertThat(payload).contains("\"agent_id\":\"agent-1\"");
        assertThat(payload).contains("\"adapter\":\"echo\"");

        verify(redis, never()).opsForList();
    }

    @Test
    void listModeFallsBackToLeftPush() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ListOperations<String, String> list = mock(ListOperations.class);
        when(redis.opsForList()).thenReturn(list);
        when(list.leftPush(anyString(), anyString())).thenReturn(1L);

        JobProducer producer = new JobProducer(
                redis, objectMapper(), props("list"), noopTracer(), noopPropagator());
        producer.enqueue("run-2", "agent-2", "echo");

        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> jsonCaptor = ArgumentCaptor.forClass(String.class);
        verify(list).leftPush(keyCaptor.capture(), jsonCaptor.capture());
        assertThat(keyCaptor.getValue()).isEqualTo("test:agentflow:jobs:runs");
        assertThat(jsonCaptor.getValue()).contains("\"run_id\":\"run-2\"");
        verify(redis, never()).opsForStream();
    }

    private static Tracer noopTracer() {
        return mock(Tracer.class);
    }

    private static Propagator noopPropagator() {
        return mock(Propagator.class);
    }
}
