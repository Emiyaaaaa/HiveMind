package io.agentflow.api.dto;

import java.util.List;

public record HealthResponse(String status, String version, List<String> adapters) {
}
