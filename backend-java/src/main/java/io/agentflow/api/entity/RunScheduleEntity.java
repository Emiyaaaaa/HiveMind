package io.agentflow.api.entity;

import com.github.f4b6a3.ulid.UlidCreator;
import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

@Entity
@Table(name = "run_schedules")
public class RunScheduleEntity {

    @Id
    @Column(length = 26)
    private String id;

    @Column(name = "tenant_id", nullable = false, length = 64)
    private String tenantId = "default";

    @Column(name = "project_id", length = 26)
    private String projectId;

    @Column(name = "agent_id", nullable = false, length = 26)
    private String agentId;

    @Column(length = 256)
    private String name;

    @Column(length = 128)
    private String cron;

    @Column(name = "interval_seconds")
    private Integer intervalSeconds;

    @Column(nullable = false, length = 64)
    private String timezone = "UTC";

    @Convert(converter = JsonMapConverter.class)
    @Column(nullable = false, columnDefinition = "json")
    private Map<String, Object> input = new HashMap<>();

    @Convert(converter = JsonMapConverter.class)
    @Column(name = "metadata", nullable = false, columnDefinition = "json")
    private Map<String, Object> metadata = new HashMap<>();

    @Column(length = 64)
    private String adapter;

    @Column(nullable = false)
    private boolean enabled = true;

    @Column(name = "next_run_at", nullable = false)
    private Instant nextRunAt;

    @Column(name = "last_run_at")
    private Instant lastRunAt;

    @Column(name = "last_run_id", length = 26)
    private String lastRunId;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @PrePersist
    void onCreate() {
        if (id == null) {
            id = UlidCreator.getUlid().toString();
        }
        Instant now = Instant.now();
        if (createdAt == null) {
            createdAt = now;
        }
        updatedAt = now;
        if (input == null) {
            input = new HashMap<>();
        }
        if (metadata == null) {
            metadata = new HashMap<>();
        }
        if (timezone == null || timezone.isBlank()) {
            timezone = "UTC";
        }
    }

    @PreUpdate
    void onUpdate() {
        updatedAt = Instant.now();
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getTenantId() {
        return tenantId;
    }

    public void setTenantId(String tenantId) {
        this.tenantId = tenantId;
    }

    public String getProjectId() {
        return projectId;
    }

    public void setProjectId(String projectId) {
        this.projectId = projectId;
    }

    public String getAgentId() {
        return agentId;
    }

    public void setAgentId(String agentId) {
        this.agentId = agentId;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getCron() {
        return cron;
    }

    public void setCron(String cron) {
        this.cron = cron;
    }

    public Integer getIntervalSeconds() {
        return intervalSeconds;
    }

    public void setIntervalSeconds(Integer intervalSeconds) {
        this.intervalSeconds = intervalSeconds;
    }

    public String getTimezone() {
        return timezone;
    }

    public void setTimezone(String timezone) {
        this.timezone = timezone;
    }

    public Map<String, Object> getInput() {
        return input == null ? Map.of() : input;
    }

    public void setInput(Map<String, Object> input) {
        this.input = input;
    }

    public Map<String, Object> getMetadata() {
        return metadata == null ? Map.of() : metadata;
    }

    public void setMetadata(Map<String, Object> metadata) {
        this.metadata = metadata;
    }

    public String getAdapter() {
        return adapter;
    }

    public void setAdapter(String adapter) {
        this.adapter = adapter;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public Instant getNextRunAt() {
        return nextRunAt;
    }

    public void setNextRunAt(Instant nextRunAt) {
        this.nextRunAt = nextRunAt;
    }

    public Instant getLastRunAt() {
        return lastRunAt;
    }

    public void setLastRunAt(Instant lastRunAt) {
        this.lastRunAt = lastRunAt;
    }

    public String getLastRunId() {
        return lastRunId;
    }

    public void setLastRunId(String lastRunId) {
        this.lastRunId = lastRunId;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Instant updatedAt) {
        this.updatedAt = updatedAt;
    }
}
