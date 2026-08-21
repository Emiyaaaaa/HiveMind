package io.agentflow.api.service;

import io.agentflow.api.dto.CheckpointResponse;
import io.agentflow.api.dto.MessageResponse;
import io.agentflow.api.dto.RunCreateRequest;
import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.dto.RunResumeRequest;
import io.agentflow.api.dto.RunRetryRequest;
import io.agentflow.api.entity.CheckpointEntity;
import io.agentflow.api.dto.StepResponse;
import io.agentflow.api.dto.ToolCallResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.entity.StepEntity;
import io.agentflow.api.entity.ToolCallEntity;
import io.agentflow.api.jobs.CancelSignal;
import io.agentflow.api.jobs.JobProducer;
import io.agentflow.api.repository.CheckpointRepository;
import io.agentflow.api.repository.MessageRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.repository.StepRepository;
import io.agentflow.api.repository.ToolCallRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * The Java equivalent of {@code app.services.run_service.RunService}. The
 * Java layer is intentionally lighter than the Python one: it only owns
 * {@link RunStatus#PENDING} and {@link RunStatus#CANCELLED} transitions
 * driven by the API. Every other state mutation belongs to the worker.
 */
@Service
public class RunService {

    private static final String INTERNAL_METADATA_KEY = "_agentflow";
    private static final String AGENT_VERSION_METADATA_KEY = "agent_version";

    private final RunRepository runs;
    private final StepRepository steps;
    private final MessageRepository messages;
    private final ToolCallRepository toolCalls;
    private final CheckpointRepository checkpoints;
    private final AgentService agentService;
    private final JobProducer jobProducer;
    private final CancelSignal cancelSignal;

    public RunService(
            RunRepository runs,
            StepRepository steps,
            MessageRepository messages,
            ToolCallRepository toolCalls,
            CheckpointRepository checkpoints,
            AgentService agentService,
            JobProducer jobProducer,
            CancelSignal cancelSignal) {
        this.runs = runs;
        this.steps = steps;
        this.messages = messages;
        this.toolCalls = toolCalls;
        this.checkpoints = checkpoints;
        this.agentService = agentService;
        this.jobProducer = jobProducer;
        this.cancelSignal = cancelSignal;
    }

    @Transactional
    public RunResponse create(RunCreateRequest req) {
        AccessControl.require(Role.OPERATOR);
        AgentEntity agent = agentService.getEntity(req.getAgentId());
        String adapter = (req.getAdapter() != null && !req.getAdapter().isBlank())
                ? req.getAdapter()
                : agent.getAdapter();

        RunEntity run = new RunEntity();
        run.setTenantId(agent.getTenantId());
        run.setAgentId(agent.getId());
        run.setAdapter(adapter);
        run.setStatus(RunStatus.PENDING);
        run.setInput(new HashMap<>(req.getInput()));
        Map<String, Object> metadata = new HashMap<>(req.getMetadata());
        metadata.put(
                INTERNAL_METADATA_KEY,
                Map.of(AGENT_VERSION_METADATA_KEY, agent.getVersion()));
        run.setMetadata(metadata);
        RunEntity saved = runs.save(run);
        enqueueJobAfterCommit(saved.getId(), agent.getId(), adapter);

        return toResponse(saved);
    }

    /** Persist server-pinned candidate Runs without dispatching them yet. */
    @Transactional
    public List<RunEntity> createPinnedCopies(
            String agentId,
            String adapter,
            int agentVersion,
            List<Map<String, Object>> inputs) {
        AccessControl.require(Role.OPERATOR);
        AgentEntity agent = agentService.getEntity(agentId);
        List<RunEntity> candidates = new ArrayList<>(inputs.size());
        for (Map<String, Object> input : inputs) {
            RunEntity run = new RunEntity();
            run.setTenantId(agent.getTenantId());
            run.setAgentId(agentId);
            run.setAdapter(adapter);
            run.setStatus(RunStatus.PENDING);
            run.setInput(new HashMap<>(input));
            run.setMetadata(Map.of(
                    INTERNAL_METADATA_KEY,
                    Map.of(AGENT_VERSION_METADATA_KEY, agentVersion)));
            candidates.add(run);
        }
        return List.copyOf(runs.saveAll(candidates));
    }

    /** Dispatch already-committed candidate Runs after their Redis manifest exists. */
    public void enqueueCandidates(List<RunEntity> candidates) {
        candidates.forEach(run ->
                jobProducer.enqueue(run.getId(), run.getAgentId(), run.getAdapter()));
    }

    @Transactional(readOnly = true)
    public List<RunResponse> list(int limit) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        int capped = Math.max(1, Math.min(limit, 200));
        // Header rows only — matches Python list_runs (no steps/messages/checkpoints).
        return runs.findRecentByTenantId(tenantId, PageRequest.of(0, capped)).stream()
                .map(RunResponse::fromEntity)
                .toList();
    }

    @Transactional(readOnly = true)
    public RunResponse get(String id) {
        return toResponse(requireRun(id, Role.VIEWER));
    }

    /** Ensure the run exists in the caller's tenant (for SSE and cross-service checks). */
    @Transactional(readOnly = true)
    public void requireAccessible(String id) {
        requireRun(id, Role.VIEWER);
    }

    @Transactional
    public void cancel(String id) {
        RunEntity run = requireRun(id, Role.OPERATOR);
        cancelSignal.requestCancel(run.getId());
        // We do not flip the row to CANCELLED here: the worker owns the
        // transition so steps/messages can be flushed first.
    }

    @Transactional
    public RunResponse retry(String id, RunRetryRequest req) {
        RunEntity run = requireRun(id, Role.OPERATOR);
        if (run.getStatus() != RunStatus.FAILED) {
            throw new RunConflictException(
                    "Cannot retry run " + id + " in status " + run.getStatus().wire());
        }

        List<CheckpointEntity> cps = checkpoints.findAllByRunIdOrderByIndexAsc(run.getId());
        Map<String, Object> checkpointState = null;
        Integer checkpointIndex = null;
        if (!cps.isEmpty()) {
            Integer requested = req != null ? req.getCheckpointIndex() : null;
            CheckpointEntity chosen;
            if (requested != null) {
                chosen = cps.stream()
                        .filter(cp -> cp.getIndex() == requested)
                        .findFirst()
                        .orElseThrow(() -> new RunConflictException(
                                "Cannot retry run " + id + " (checkpoint " + requested + " missing)"));
            } else {
                chosen = cps.get(cps.size() - 1);
            }
            checkpointState = chosen.getState();
            checkpointIndex = chosen.getIndex();
        }

        Map<String, Object> meta = ResumeMetadata.withoutResume(run.getMetadata());
        ResumeMetadata.mergeInto(
                meta, ResumeMetadata.retry(checkpointState, checkpointIndex));
        run.setStatus(RunStatus.PENDING);
        run.setError(null);
        run.setMetadata(meta);
        RunEntity saved = runs.save(run);
        enqueueJobAfterCommit(saved.getId(), saved.getAgentId(), saved.getAdapter());
        return toResponse(saved);
    }

    @Transactional
    public RunResponse resume(String id, RunResumeRequest req) {
        RunEntity run = requireRun(id, Role.OPERATOR);
        if (run.getStatus() != RunStatus.WAITING_HUMAN) {
            throw new RunConflictException(
                    "Cannot resume run " + id + " in status " + run.getStatus().wire());
        }

        Map<String, Object> humanInput =
                req != null && req.getInput() != null ? req.getInput() : Map.of();
        if (!humanInput.isEmpty()) {
            Map<String, Object> merged = new HashMap<>(run.getInput());
            merged.putAll(humanInput);
            run.setInput(merged);
        }

        List<CheckpointEntity> cps = checkpoints.findAllByRunIdOrderByIndexAsc(run.getId());
        Map<String, Object> checkpointState = null;
        Integer checkpointIndex = null;
        if (!cps.isEmpty()) {
            CheckpointEntity latest = cps.get(cps.size() - 1);
            checkpointState = latest.getState();
            checkpointIndex = latest.getIndex();
        }

        Map<String, Object> meta = ResumeMetadata.withoutResume(run.getMetadata());
        ResumeMetadata.mergeInto(
                meta, ResumeMetadata.resume(checkpointState, checkpointIndex, humanInput));
        run.setStatus(RunStatus.PENDING);
        run.setMetadata(meta);
        RunEntity saved = runs.save(run);
        enqueueJobAfterCommit(saved.getId(), saved.getAgentId(), saved.getAdapter());
        return toResponse(saved);
    }

    private RunEntity requireRun(String id, Role minimum) {
        String tenantId = AccessControl.tenantId(minimum);
        return runs.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RunNotFoundException(id));
    }

    /**
     * Enqueue only after the run row is committed so the worker never sees a
     * job for a run that is not yet visible outside this transaction.
     */
    private void enqueueJobAfterCommit(String runId, String agentId, String adapter) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            jobProducer.enqueue(runId, agentId, adapter);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                jobProducer.enqueue(runId, agentId, adapter);
            }
        });
    }

    private RunResponse toResponse(RunEntity run) {
        List<StepEntity> stepEntities = steps.findAllByRunIdOrderByIndexAsc(run.getId());
        List<String> stepIds = stepEntities.stream().map(StepEntity::getId).toList();
        Map<String, List<ToolCallResponse>> toolsByStep = stepIds.isEmpty()
                ? Map.of()
                : toolCalls.findAllByStepIdInOrderByCreatedAtAsc(stepIds).stream()
                        .collect(Collectors.groupingBy(
                                ToolCallEntity::getStepId,
                                Collectors.mapping(ToolCallResponse::fromEntity, Collectors.toList())));
        List<StepResponse> stepDtos = stepEntities.stream()
                .map(s -> StepResponse.fromEntity(s, toolsByStep.getOrDefault(s.getId(), List.of())))
                .toList();
        List<MessageResponse> messageDtos = messages.findAllByRunIdOrderByIndexAsc(run.getId())
                .stream()
                .map(MessageResponse::fromEntity)
                .toList();
        List<CheckpointResponse> checkpointDtos = checkpoints.findAllByRunIdOrderByIndexAsc(run.getId())
                .stream()
                .map(CheckpointResponse::fromEntity)
                .toList();
        return RunResponse.fromEntity(run, stepDtos, messageDtos, checkpointDtos);
    }
}
