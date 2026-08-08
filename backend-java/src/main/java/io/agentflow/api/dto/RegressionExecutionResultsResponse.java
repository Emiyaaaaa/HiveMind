package io.agentflow.api.dto;

import java.util.List;

public record RegressionExecutionResultsResponse(
        String executionId,
        boolean passed,
        int totalCases,
        int passedCases,
        int failedCases,
        List<CaseResult> cases) {

    public record CaseResult(
            String baselineRunId,
            String candidateRunId,
            boolean passed,
            List<Failure> failures) {}

    public record Failure(String code, String message) {}
}
