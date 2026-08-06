package io.agentflow.api.service;

import java.util.List;

record RegressionExecutionManifest(
        String executionId,
        int candidateAgentVersion,
        List<CaseReference> cases) {

    record CaseReference(String baselineRunId, String candidateRunId) {}
}
