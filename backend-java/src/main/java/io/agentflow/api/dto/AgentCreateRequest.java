package io.agentflow.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.Map;

public class AgentCreateRequest {

    @NotBlank
    @Size(min = 1, max = 128)
    private String name;

    private String description;

    private String adapter = "echo";

    private Map<String, Object> config;

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public String getAdapter() {
        return adapter == null || adapter.isBlank() ? "echo" : adapter;
    }

    public void setAdapter(String adapter) {
        this.adapter = adapter;
    }

    public Map<String, Object> getConfig() {
        return config == null ? Map.of() : config;
    }

    public void setConfig(Map<String, Object> config) {
        this.config = config;
    }
}
