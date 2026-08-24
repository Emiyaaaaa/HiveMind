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
    private Auth auth = new Auth();
    private Temporal temporal = new Temporal();

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

    public Auth getAuth() {
        return auth;
    }

    public void setAuth(Auth auth) {
        this.auth = auth;
    }

    public Temporal getTemporal() {
        return temporal;
    }

    public void setTemporal(Temporal temporal) {
        this.temporal = temporal;
    }

    public static class Auth {
        private boolean enabled = false;
        private List<ApiKeyEntry> keys = List.of();

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public List<ApiKeyEntry> getKeys() {
            return keys;
        }

        public void setKeys(List<ApiKeyEntry> keys) {
            this.keys = keys == null ? List.of() : keys;
        }
    }

    public static class ApiKeyEntry {
        private String key;
        private String tenantId = "default";
        private String role = "admin";

        public String getKey() {
            return key;
        }

        public void setKey(String key) {
            this.key = key;
        }

        public String getTenantId() {
            return tenantId;
        }

        public void setTenantId(String tenantId) {
            this.tenantId = tenantId;
        }

        public String getRole() {
            return role;
        }

        public void setRole(String role) {
            this.role = role;
        }
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
         * Must match the Python side's {@code AGENTFLOW_JOBS_IMPL}.
         * <ul>
         *   <li>{@code streams} (default) -> {@code XADD} onto a Redis stream
         *       with at-least-once delivery via XACK + XAUTOCLAIM.</li>
         *   <li>{@code list} -> legacy {@code LPUSH} + {@code BRPOP}.</li>
         *   <li>{@code temporal} -> start or signal a durable Temporal workflow
         *       for the run; worker restarts resume from checkpoints.</li>
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

    public static class Temporal {
        private String target = "localhost:7233";
        private String namespace = "default";
        private String taskQueue = "agentflow-runs";
        private long activityHeartbeatSeconds = 30;
        private long activityStartToCloseSeconds = 7 * 24 * 3600;
        private int activityMaxAttempts = 5;

        public String getTarget() {
            return target;
        }

        public void setTarget(String target) {
            this.target = target;
        }

        public String getNamespace() {
            return namespace;
        }

        public void setNamespace(String namespace) {
            this.namespace = namespace;
        }

        public String getTaskQueue() {
            return taskQueue;
        }

        public void setTaskQueue(String taskQueue) {
            this.taskQueue = taskQueue;
        }

        public long getActivityHeartbeatSeconds() {
            return activityHeartbeatSeconds;
        }

        public void setActivityHeartbeatSeconds(long activityHeartbeatSeconds) {
            this.activityHeartbeatSeconds = activityHeartbeatSeconds;
        }

        public long getActivityStartToCloseSeconds() {
            return activityStartToCloseSeconds;
        }

        public void setActivityStartToCloseSeconds(long activityStartToCloseSeconds) {
            this.activityStartToCloseSeconds = activityStartToCloseSeconds;
        }

        public int getActivityMaxAttempts() {
            return activityMaxAttempts;
        }

        public void setActivityMaxAttempts(int activityMaxAttempts) {
            this.activityMaxAttempts = activityMaxAttempts;
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
        private String streamSuffix = ":log";
        private int streamMaxLen = 10_000;
        private long sseHeartbeatSeconds = 15;

        public String getChannelPrefix() {
            return channelPrefix;
        }

        public void setChannelPrefix(String channelPrefix) {
            this.channelPrefix = channelPrefix;
        }

        public String getStreamSuffix() {
            return streamSuffix;
        }

        public void setStreamSuffix(String streamSuffix) {
            this.streamSuffix = streamSuffix;
        }

        public int getStreamMaxLen() {
            return streamMaxLen;
        }

        public void setStreamMaxLen(int streamMaxLen) {
            this.streamMaxLen = streamMaxLen;
        }

        public long getSseHeartbeatSeconds() {
            return sseHeartbeatSeconds;
        }

        public void setSseHeartbeatSeconds(long sseHeartbeatSeconds) {
            this.sseHeartbeatSeconds = sseHeartbeatSeconds;
        }
    }
}
