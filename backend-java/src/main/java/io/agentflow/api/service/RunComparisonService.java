package io.agentflow.api.service;

import io.agentflow.api.dto.RunComparisonPreviewRequest;
import io.agentflow.api.dto.RunComparisonResponse;
import io.agentflow.api.dto.RunComparisonResponse.RunSide;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RunComparisonService {

    private final RunRepository runs;

    public RunComparisonService(RunRepository runs) {
        this.runs = runs;
    }

    @Transactional(readOnly = true)
    public RunComparisonResponse preview(RunComparisonPreviewRequest request) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        String baselineId = normalizedId(
                request == null ? null : request.baselineRunId(), "baseline_run_id");
        String candidateId = normalizedId(
                request == null ? null : request.candidateRunId(), "candidate_run_id");
        if (baselineId.equals(candidateId)) {
            throw new RunComparisonValidationException(
                    "Baseline and candidate run IDs must differ.");
        }

        RunEntity baseline = runs.findByIdAndTenantId(baselineId, tenantId)
                .orElseThrow(() -> new RunNotFoundException(baselineId));
        RunEntity candidate = runs.findByIdAndTenantId(candidateId, tenantId)
                .orElseThrow(() -> new RunNotFoundException(candidateId));
        if (!Objects.equals(baseline.getAgentId(), candidate.getAgentId())) {
            throw new RunComparisonValidationException(
                    "Runs must belong to the same agent.");
        }
        requireTerminal(baseline, candidate);

        Integer baselineVersion = agentVersion(baseline.getMetadata());
        Integer candidateVersion = agentVersion(candidate.getMetadata());
        String baselineStatus = baseline.getStatus().wire();
        String candidateStatus = candidate.getStatus().wire();
        return new RunComparisonResponse(
                side(baseline, baselineVersion),
                side(candidate, candidateVersion),
                !Objects.equals(baselineVersion, candidateVersion),
                !Objects.equals(baselineStatus, candidateStatus),
                !Objects.equals(baseline.getError(), candidate.getError()),
                !Objects.equals(baseline.getInput(), candidate.getInput()),
                !Objects.equals(baseline.getOutput(), candidate.getOutput()));
    }

    private static RunSide side(RunEntity run, Integer version) {
        return new RunSide(
                run.getId(),
                run.getAgentId(),
                version,
                run.getStatus().wire(),
                run.getError());
    }

    private static Integer agentVersion(Map<String, Object> metadata) {
        if (metadata == null || !(metadata.get("_agentflow") instanceof Map<?, ?> internal)) {
            return null;
        }
        Object raw = internal.get("agent_version");
        if (!(raw instanceof Byte
                || raw instanceof Short
                || raw instanceof Integer
                || raw instanceof Long
                || raw instanceof BigInteger)) {
            return null;
        }
        try {
            int version = new BigInteger(raw.toString()).intValueExact();
            return version > 0 ? version : null;
        } catch (ArithmeticException | NumberFormatException ignored) {
            return null;
        }
    }

    private static String normalizedId(String value, String field) {
        String normalized = value == null ? "" : value.strip();
        if (normalized.isEmpty()) {
            throw new RunComparisonValidationException(field + " must not be blank.");
        }
        return normalized;
    }

    private static void requireTerminal(RunEntity baseline, RunEntity candidate) {
        List<String> nonTerminal = new ArrayList<>();
        if (!isTerminal(baseline.getStatus())) {
            nonTerminal.add(baseline.getId() + " (" + baseline.getStatus().wire() + ")");
        }
        if (!isTerminal(candidate.getStatus())) {
            nonTerminal.add(candidate.getId() + " (" + candidate.getStatus().wire() + ")");
        }
        if (!nonTerminal.isEmpty()) {
            throw new RunConflictException(
                    "Both runs must be terminal; non-terminal runs: "
                            + String.join(", ", nonTerminal));
        }
    }

    private static boolean isTerminal(RunStatus status) {
        return status == RunStatus.SUCCEEDED
                || status == RunStatus.FAILED
                || status == RunStatus.CANCELLED;
    }
}
