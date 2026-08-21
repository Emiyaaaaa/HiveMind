package io.agentflow.api.service;

import com.github.f4b6a3.ulid.UlidCreator;
import io.agentflow.api.dto.RegressionExecutionCreateRequest;
import io.agentflow.api.dto.RegressionExecutionResponse;
import io.agentflow.api.dto.RegressionExecutionResponse.RunPair;
import io.agentflow.api.dto.RegressionExecutionResultsResponse;
import io.agentflow.api.dto.RegressionExecutionResultsResponse.CaseResult;
import io.agentflow.api.dto.RegressionExecutionResultsResponse.Failure;
import io.agentflow.api.dto.RunComparisonPreviewRequest;
import io.agentflow.api.dto.RunComparisonResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.AgentVersionEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.AgentVersionRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import io.agentflow.api.service.RegressionExecutionManifest.CaseReference;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.springframework.stereotype.Service;

@Service
public class RegressionExecutionService {

    private static final int MAX_CASES = 100;

    private final RunRepository runs;
    private final AgentVersionRepository versions;
    private final AgentService agents;
    private final RunService runService;
    private final RegressionExecutionStore store;
    private final RunComparisonService comparisons;

    public RegressionExecutionService(
            RunRepository runs,
            AgentVersionRepository versions,
            AgentService agents,
            RunService runService,
            RegressionExecutionStore store,
            RunComparisonService comparisons) {
        this.runs = runs;
        this.versions = versions;
        this.agents = agents;
        this.runService = runService;
        this.store = store;
        this.comparisons = comparisons;
    }

    public RegressionExecutionResponse create(RegressionExecutionCreateRequest request) {
        AccessControl.require(Role.OPERATOR);
        String tenantId = AccessControl.tenantId(Role.OPERATOR);
        List<String> baselineIds = normalizeIds(request);
        List<RunEntity> baselines = baselineIds.stream()
                .map(id -> runs.findByIdAndTenantId(id, tenantId)
                        .orElseThrow(() -> new RunNotFoundException(id)))
                .toList();
        validateBaselines(baselines);

        String agentId = baselines.getFirst().getAgentId();
        AgentEntity agent = agents.getEntity(agentId);
        int candidateVersion = agent.getVersion();
        AgentVersionEntity snapshot = versions.findByAgentIdAndVersion(agentId, candidateVersion)
                .orElseThrow(() -> new AgentVersionNotFoundException(candidateVersion));
        List<Map<String, Object>> inputs = baselines.stream()
                .<Map<String, Object>>map(run -> new HashMap<>(run.getInput()))
                .toList();
        List<RunEntity> candidates = runService.createPinnedCopies(
                agentId, snapshot.getAdapter(), candidateVersion, inputs);
        if (candidates.size() != baselines.size()) {
            throw new IllegalStateException("Candidate Run count does not match baseline count");
        }

        List<CaseReference> cases = new ArrayList<>(baselines.size());
        for (int index = 0; index < baselines.size(); index++) {
            cases.add(new CaseReference(
                    baselines.get(index).getId(), candidates.get(index).getId()));
        }
        RegressionExecutionManifest manifest = new RegressionExecutionManifest(
                "reg_" + UlidCreator.getUlid(),
                candidateVersion,
                List.copyOf(cases));
        try {
            store.save(manifest);
        } catch (RuntimeException ex) {
            runs.deleteAll(candidates);
            throw ex;
        }
        runService.enqueueCandidates(candidates);
        return response(manifest, byId(candidates));
    }

    public RegressionExecutionResponse get(String executionId) {
        RegressionExecutionManifest manifest = manifest(executionId);
        return response(manifest, candidateRuns(manifest));
    }

    public RegressionExecutionResultsResponse results(String executionId) {
        RegressionExecutionManifest manifest = manifest(executionId);
        Map<String, RunEntity> candidates = candidateRuns(manifest);
        if (candidates.values().stream().anyMatch(run -> !isTerminal(run.getStatus()))) {
            throw new RunConflictException(
                    "Regression execution is not complete: " + manifest.executionId());
        }

        List<CaseResult> results = new ArrayList<>(manifest.cases().size());
        int passed = 0;
        for (CaseReference item : manifest.cases()) {
            RunComparisonResponse comparison = comparisons.preview(
                    new RunComparisonPreviewRequest(
                            item.baselineRunId(), item.candidateRunId()));
            List<Failure> failures = evaluate(comparison);
            boolean casePassed = failures.isEmpty();
            if (casePassed) {
                passed++;
            }
            results.add(new CaseResult(
                    item.baselineRunId(),
                    item.candidateRunId(),
                    casePassed,
                    failures));
        }
        int total = results.size();
        return new RegressionExecutionResultsResponse(
                manifest.executionId(),
                passed == total,
                total,
                passed,
                total - passed,
                List.copyOf(results));
    }

    private RegressionExecutionManifest manifest(String executionId) {
        String normalized = executionId == null ? "" : executionId.strip();
        if (normalized.isEmpty()) {
            throw RegressionExecutionException.notFound(normalized);
        }
        return store.find(normalized)
                .orElseThrow(() -> RegressionExecutionException.notFound(normalized));
    }

    private Map<String, RunEntity> candidateRuns(RegressionExecutionManifest manifest) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        List<String> ids = manifest.cases().stream()
                .map(CaseReference::candidateRunId)
                .toList();
        Map<String, RunEntity> result = new HashMap<>();
        for (String id : ids) {
            RunEntity run = runs.findByIdAndTenantId(id, tenantId)
                    .orElseThrow(() -> new RunNotFoundException(id));
            result.put(id, run);
        }
        return result;
    }

    private static RegressionExecutionResponse response(
            RegressionExecutionManifest manifest, Map<String, RunEntity> candidates) {
        List<RunPair> cases = manifest.cases().stream()
                .map(item -> new RunPair(item.baselineRunId(), item.candidateRunId()))
                .toList();
        int completed = (int) candidates.values().stream()
                .filter(run -> isTerminal(run.getStatus()))
                .count();
        int total = candidates.size();
        boolean allPending = candidates.values().stream()
                .allMatch(run -> run.getStatus() == RunStatus.PENDING);
        String status = completed == total ? "completed" : allPending ? "pending" : "running";
        return new RegressionExecutionResponse(
                manifest.executionId(),
                manifest.candidateAgentVersion(),
                status,
                total,
                completed,
                cases);
    }

    private static List<Failure> evaluate(RunComparisonResponse comparison) {
        List<Failure> failures = new ArrayList<>();
        if (comparison.statusChanged()) {
            failures.add(new Failure("status_changed", "Candidate status differs from baseline"));
        }
        if (comparison.errorChanged()) {
            failures.add(new Failure("error_changed", "Candidate error differs from baseline"));
        }
        return List.copyOf(failures);
    }

    private static List<String> normalizeIds(RegressionExecutionCreateRequest request) {
        if (request == null
                || request.baselineRunIds() == null
                || request.baselineRunIds().isEmpty()) {
            throw RegressionExecutionException.invalid(
                    "baseline_run_ids must contain at least one Run ID");
        }
        if (request.baselineRunIds().size() > MAX_CASES) {
            throw RegressionExecutionException.invalid(
                    "baseline_run_ids must contain at most 100 Run IDs");
        }
        LinkedHashSet<String> ids = new LinkedHashSet<>();
        for (String raw : request.baselineRunIds()) {
            String id = raw == null ? "" : raw.strip();
            if (id.isEmpty()) {
                throw RegressionExecutionException.invalid(
                        "baseline_run_ids must not contain blank values");
            }
            if (!ids.add(id)) {
                throw RegressionExecutionException.invalid(
                        "baseline_run_ids must not contain duplicates");
            }
        }
        return List.copyOf(ids);
    }

    private static void validateBaselines(List<RunEntity> baselines) {
        String agentId = baselines.getFirst().getAgentId();
        if (baselines.stream().anyMatch(run -> !Objects.equals(agentId, run.getAgentId()))) {
            throw RegressionExecutionException.invalid(
                    "Baseline runs must belong to the same agent");
        }
        List<String> nonTerminal = baselines.stream()
                .filter(run -> !isTerminal(run.getStatus()))
                .map(run -> run.getId() + " (" + run.getStatus().wire() + ")")
                .toList();
        if (!nonTerminal.isEmpty()) {
            throw new RunConflictException(
                    "All baseline runs must be terminal; non-terminal runs: "
                            + String.join(", ", nonTerminal));
        }
    }

    private static Map<String, RunEntity> byId(Iterable<RunEntity> values) {
        Map<String, RunEntity> result = new HashMap<>();
        values.forEach(run -> result.put(run.getId(), run));
        return result;
    }

    private static boolean isTerminal(RunStatus status) {
        return status == RunStatus.SUCCEEDED
                || status == RunStatus.FAILED
                || status == RunStatus.CANCELLED;
    }
}
