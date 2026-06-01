package io.agentflow.api.config;

import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "agentflow")
public class AgentflowProperties {

    private String version = "0.1.0";
    private List<String> adapters = List.of("echo", "langgraph");
    private Jobs jobs = new Jobs();
    private Cancel cancel = new Cancel();
    private Events events = new Events();
    private Otel otel = new Otel();

    public String getVersion() {
        return version;
    }

    public void setVersion(String version) {
        this.version = version;
    }

    public List<String> getAdapters() {
        return adapters;
    }

    public void setAdapters(List<String> adapters) {
        this.adapters = adapters;
    }

    public Jobs getJobs() {
        return jobs;
    }

    public void setJobs(Jobs jobs) {
        this.jobs = jobs;
    }

    public Cancel getCancel() {
        return cancel;
    }

    public void setCancel(Cancel cancel) {
        this.cancel = cancel;
    }

    public Events getEvents() {
        return events;
    }

    public void setEvents(Events events) {
        this.events = events;
    }

    public Otel getOtel() {
        return otel;
    }

    public void setOtel(Otel otel) {
        this.otel = otel;
    }

    public static class Otel {
        private boolean enabled = false;
        private String serviceName = "agentflow-api";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getServiceName() {
            return serviceName;
        }

        public void setServiceName(String serviceName) {
            this.serviceName = serviceName;
        }
    }

    public static class Jobs {
        /**
         * Wire protocol used to enqueue run jobs for the Python worker.
         * Must match the Python side's {@code AGENTFLOW_REDIS_QUEUE_IMPL}.
         * <ul>
         *   <li>{@code streams} (default) -> {@code XADD} onto a Redis stream
         *       with at-least-once delivery via XACK + XAUTOCLAIM.</li>
         *   <li>{@code list} -> legacy {@code LPUSH} + {@code BRPOP}.</li>
         * </ul>
         */
        private String impl = "streams";
        private String queueKey = "agentflow:jobs:runs";

        public String getImpl() {
            return impl;
        }

        public void setImpl(String impl) {
            this.impl = impl;
        }

        public String getQueueKey() {
            return queueKey;
        }

        public void setQueueKey(String queueKey) {
            this.queueKey = queueKey;
        }
    }

    public static class Cancel {
        private String keyPrefix = "agentflow:cancel:";
        private long ttlSeconds = 86400;

        public String getKeyPrefix() {
            return keyPrefix;
        }

        public void setKeyPrefix(String keyPrefix) {
            this.keyPrefix = keyPrefix;
        }

        public long getTtlSeconds() {
            return ttlSeconds;
        }

        public void setTtlSeconds(long ttlSeconds) {
            this.ttlSeconds = ttlSeconds;
        }
    }

    public static class Events {
        private String channelPrefix = "agentflow:run:";
        private long sseHeartbeatSeconds = 15;

        public String getChannelPrefix() {
            return channelPrefix;
        }

        public void setChannelPrefix(String channelPrefix) {
            this.channelPrefix = channelPrefix;
        }

        public long getSseHeartbeatSeconds() {
            return sseHeartbeatSeconds;
        }

        public void setSseHeartbeatSeconds(long sseHeartbeatSeconds) {
            this.sseHeartbeatSeconds = sseHeartbeatSeconds;
        }
    }
}
