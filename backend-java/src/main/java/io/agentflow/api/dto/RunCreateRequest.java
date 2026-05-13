package io.agentflow.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import java.util.Map;

public class RunCreateRequest {

    @NotBlank
    @JsonProperty("agent_id")
    private String agentId;

    private Map<String, Object> input;

    private Map<String, Object> metadata;

    /**
     * Optional override of the agent's default adapter for this run.
     */
    private String adapter;

    public String getAgentId() {
        return agentId;
    }

    public void setAgentId(String agentId) {
        this.agentId = agentId;
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
}
