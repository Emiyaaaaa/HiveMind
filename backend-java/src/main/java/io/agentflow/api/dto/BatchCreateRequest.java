package io.agentflow.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;

public class BatchCreateRequest {

    @NotBlank
    @JsonProperty("agent_id")
    private String agentId;

    @NotEmpty
    @Size(max = 100)
    @Valid
    private List<BatchItemRequest> items;

    private String adapter;

    private Map<String, Object> metadata;

    public String getAgentId() {
        return agentId;
    }

    public void setAgentId(String agentId) {
        this.agentId = agentId;
    }

    public List<BatchItemRequest> getItems() {
        return items;
    }

    public void setItems(List<BatchItemRequest> items) {
        this.items = items;
    }

    public String getAdapter() {
        return adapter;
    }

    public void setAdapter(String adapter) {
        this.adapter = adapter;
    }

    public Map<String, Object> getMetadata() {
        return metadata == null ? Map.of() : metadata;
    }

    public void setMetadata(Map<String, Object> metadata) {
        this.metadata = metadata;
    }

    public static class BatchItemRequest {
        private Map<String, Object> input;
        private Map<String, Object> metadata;

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
    }
}
