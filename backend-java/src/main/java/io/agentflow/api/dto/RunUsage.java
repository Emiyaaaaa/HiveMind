package io.agentflow.api.dto;

import io.agentflow.api.entity.RunStatus;
import java.util.List;
import java.util.Map;

public class RunUsage {

    private int tokensIn;
    private int tokensOut;
    private double costUsd;
    private Integer latencyMs;
    private int stepCount;
    private int failedStepCount;
    private int toolCallCount;
    private int failedToolCallCount;

    public static RunUsage empty() {
        return new RunUsage();
    }

    public static RunUsage fromSteps(List<StepResponse> steps) {
        RunUsage usage = new RunUsage();
        if (steps == null || steps.isEmpty()) {
            return usage;
        }
        int latencySum = 0;
        boolean hasLatency = false;
        for (StepResponse step : steps) {
            usage.stepCount++;
            if (step.getTokensIn() != null) {
                usage.tokensIn += step.getTokensIn();
            }
            if (step.getTokensOut() != null) {
                usage.tokensOut += step.getTokensOut();
            }
            if (step.getCostUsd() != null) {
                usage.costUsd += step.getCostUsd();
            }
            if (step.getLatencyMs() != null) {
                latencySum += step.getLatencyMs();
                hasLatency = true;
            }
            if (step.getStatus() == RunStatus.FAILED) {
                usage.failedStepCount++;
            }
            if (step.getToolCalls() != null) {
                for (ToolCallResponse call : step.getToolCalls()) {
                    usage.toolCallCount++;
                    if (call.getError() != null && !call.getError().isBlank()) {
                        usage.failedToolCallCount++;
                    }
                }
            }
        }
        usage.costUsd = Math.round(usage.costUsd * 1_000_000.0) / 1_000_000.0;
        if (hasLatency) {
            usage.latencyMs = latencySum;
        }
        return usage;
    }

    @SuppressWarnings("unchecked")
    public static RunUsage fromMetadata(Map<String, Object> metadata) {
        if (metadata == null) {
            return null;
        }
        Object raw = metadata.get("usage");
        if (!(raw instanceof Map<?, ?> map)) {
            return null;
        }
        RunUsage usage = new RunUsage();
        Object tin = map.get("tokens_in");
        if (tin instanceof Number n) {
            usage.tokensIn = n.intValue();
        }
        Object tout = map.get("tokens_out");
        if (tout instanceof Number n) {
            usage.tokensOut = n.intValue();
        }
        Object cost = map.get("cost_usd");
        if (cost instanceof Number n) {
            usage.costUsd = n.doubleValue();
        }
        Object latency = map.get("latency_ms");
        if (latency instanceof Number n) {
            usage.latencyMs = n.intValue();
        }
        Object steps = map.get("step_count");
        if (steps instanceof Number n) {
            usage.stepCount = n.intValue();
        }
        Object failedSteps = map.get("failed_step_count");
        if (failedSteps instanceof Number n) {
            usage.failedStepCount = n.intValue();
        }
        Object tools = map.get("tool_call_count");
        if (tools instanceof Number n) {
            usage.toolCallCount = n.intValue();
        }
        Object failedTools = map.get("failed_tool_call_count");
        if (failedTools instanceof Number n) {
            usage.failedToolCallCount = n.intValue();
        }
        return usage;
    }

    public int getTokensIn() {
        return tokensIn;
    }

    public int getTokensOut() {
        return tokensOut;
    }

    public double getCostUsd() {
        return costUsd;
    }

    public Integer getLatencyMs() {
        return latencyMs;
    }

    public int getStepCount() {
        return stepCount;
    }

    public int getFailedStepCount() {
        return failedStepCount;
    }

    public int getToolCallCount() {
        return toolCallCount;
    }

    public int getFailedToolCallCount() {
        return failedToolCallCount;
    }
}
