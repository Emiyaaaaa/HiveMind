package io.agentflow.api.dto;

public record RunComparisonPreviewRequest(
        String baselineRunId,
        String candidateRunId) {}
