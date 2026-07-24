package io.agentflow.api.dto;

import java.util.Map;

public class AgentVersionDiffResponse {

    private int fromVersion;
    private int toVersion;
    private Map<String, Object> adapter;
    private Map<String, Object> description;
    private Map<String, Object> config;

    public int getFromVersion() {
        return fromVersion;
    }

    public void setFromVersion(int fromVersion) {
        this.fromVersion = fromVersion;
    }

    public int getToVersion() {
        return toVersion;
    }

    public void setToVersion(int toVersion) {
        this.toVersion = toVersion;
    }

    public Map<String, Object> getAdapter() {
        return adapter;
    }

    public void setAdapter(Map<String, Object> adapter) {
        this.adapter = adapter;
    }

    public Map<String, Object> getDescription() {
        return description;
    }

    public void setDescription(Map<String, Object> description) {
        this.description = description;
    }

    public Map<String, Object> getConfig() {
        return config;
    }

    public void setConfig(Map<String, Object> config) {
        this.config = config;
    }
}
