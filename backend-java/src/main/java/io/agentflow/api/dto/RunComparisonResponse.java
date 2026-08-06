package io.agentflow.api.dto;

public record RunComparisonResponse(
        RunSide baseline,
        RunSide candidate,
        boolean agentVersionChanged,
        boolean statusChanged,
        boolean errorChanged,
        boolean inputChanged,
        boolean outputChanged) {

    public record RunSide(
            String runId,
            String agentId,
            Integer agentVersion,
            String status,
            String error) {}
}
