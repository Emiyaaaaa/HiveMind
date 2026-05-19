package io.agentflow.api.service;

import io.agentflow.api.dto.CheckpointResponse;
import io.agentflow.api.dto.MessageResponse;
import io.agentflow.api.dto.RunCreateRequest;
import io.agentflow.api.dto.RunResponse;
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
        AgentEntity agent = agentService.getEntity(req.getAgentId());
        String adapter = (req.getAdapter() != null && !req.getAdapter().isBlank())
                ? req.getAdapter()
                : agent.getAdapter();

        RunEntity run = new RunEntity();
        run.setAgentId(agent.getId());
        run.setAdapter(adapter);
        run.setStatus(RunStatus.PENDING);
        run.setInput(new HashMap<>(req.getInput()));
        run.setMetadata(new HashMap<>(req.getMetadata()));
        RunEntity saved = runs.save(run);
        enqueueJobAfterCommit(saved.getId(), agent.getId(), adapter);

        return toResponse(saved);
    }

    @Transactional(readOnly = true)
    public List<RunResponse> list(int limit) {
        int capped = Math.max(1, Math.min(limit, 200));
        // Header rows only — matches Python list_runs (no steps/messages/checkpoints).
        return runs.findRecent(PageRequest.of(0, capped)).stream()
                .map(RunResponse::fromEntity)
                .toList();
    }

    @Transactional(readOnly = true)
    public RunResponse get(String id) {
        RunEntity run = runs.findById(id).orElseThrow(() -> new RunNotFoundException(id));
        return toResponse(run);
    }

    @Transactional
    public void cancel(String id) {
        RunEntity run = runs.findById(id).orElseThrow(() -> new RunNotFoundException(id));
        cancelSignal.requestCancel(run.getId());
        // We do not flip the row to CANCELLED here: the worker owns the
        // transition so steps/messages can be flushed first.
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
