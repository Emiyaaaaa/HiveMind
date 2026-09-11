package io.agentflow.api.service;

import io.agentflow.api.dto.BatchCreateRequest;
import io.agentflow.api.dto.BatchCreateRequest.BatchItemRequest;
import io.agentflow.api.dto.BatchResponse;
import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.RunBatchEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.RunBatchRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class BatchService {

    private static final int MAX_ITEMS = 100;
    private static final String INTERNAL_METADATA_KEY = "_agentflow";
    private static final String AGENT_VERSION_METADATA_KEY = "agent_version";

    private final RunBatchRepository batches;
    private final RunRepository runs;
    private final AgentService agents;
    private final RunService runService;

    public BatchService(
            RunBatchRepository batches,
            RunRepository runs,
            AgentService agents,
            RunService runService) {
        this.batches = batches;
        this.runs = runs;
        this.agents = agents;
        this.runService = runService;
    }

    @Transactional
    public BatchResponse create(BatchCreateRequest request) {
        AccessControl.require(Role.OPERATOR);
        if (request.getItems() == null
                || request.getItems().isEmpty()
                || request.getItems().size() > MAX_ITEMS) {
            throw BatchException.invalid("items must contain 1–" + MAX_ITEMS + " entries");
        }
        AgentEntity agent = agents.getEntity(request.getAgentId());
        RunBatchEntity batch = new RunBatchEntity();
        batch.setTenantId(agent.getTenantId());
        batch.setAgentId(agent.getId());
        batch.setRunIds(new ArrayList<>());
        batch = batches.save(batch);

        List<String> runIds = new ArrayList<>(request.getItems().size());
        for (BatchItemRequest item : request.getItems()) {
            Map<String, Object> metadata = new HashMap<>(request.getMetadata());
            metadata.putAll(item.getMetadata());
            metadata.put(
                    INTERNAL_METADATA_KEY,
                    Map.of(
                            AGENT_VERSION_METADATA_KEY,
                            agent.getVersion(),
                            "batch_id",
                            batch.getId()));
            RunEntity run = runService.createTaggedRun(
                    agent, request.getAdapter(), item.getInput(), metadata);
            runIds.add(run.getId());
        }
        batch.setRunIds(runIds);
        batches.save(batch);
        return toResponse(batch);
    }

    @Transactional(readOnly = true)
    public List<BatchResponse> list(int limit) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        int capped = Math.max(1, Math.min(limit, 200));
        return batches.findRecentByTenantId(tenantId, PageRequest.of(0, capped)).stream()
                .map(this::toResponse)
                .toList();
    }

    @Transactional(readOnly = true)
    public BatchResponse get(String id) {
        return toResponse(requireBatch(id));
    }

    @Transactional(readOnly = true)
    public List<RunResponse> listRuns(String id) {
        RunBatchEntity batch = requireBatch(id);
        return runService.listByIds(batch.getRunIds());
    }

    private RunBatchEntity requireBatch(String id) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        return batches
                .findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> BatchException.notFound(id));
    }

    private BatchResponse toResponse(RunBatchEntity batch) {
        String tenantId = batch.getTenantId();
        List<RunEntity> ordered = new ArrayList<>();
        for (String runId : batch.getRunIds()) {
            runs.findByIdAndTenantId(runId, tenantId).ifPresent(ordered::add);
        }
        int total = ordered.size();
        int completed = (int) ordered.stream().filter(run -> isTerminal(run.getStatus())).count();
        boolean allPending =
                ordered.stream().allMatch(run -> run.getStatus() == RunStatus.PENDING);
        String status = total > 0 && completed == total
                ? "completed"
                : allPending ? "pending" : "running";
        return new BatchResponse(
                batch.getId(),
                batch.getAgentId(),
                status,
                total,
                completed,
                List.copyOf(batch.getRunIds()),
                batch.getCreatedAt());
    }

    private static boolean isTerminal(RunStatus status) {
        return status == RunStatus.SUCCEEDED
                || status == RunStatus.FAILED
                || status == RunStatus.CANCELLED;
    }
}
