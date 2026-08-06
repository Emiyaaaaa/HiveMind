package io.agentflow.api.dto;

import java.util.List;

public record RegressionExecutionResponse(
        String executionId,
        int candidateAgentVersion,
        String status,
        int totalCases,
        int completedCases,
        List<RunPair> cases) {

    public record RunPair(String baselineRunId, String candidateRunId) {}
}
