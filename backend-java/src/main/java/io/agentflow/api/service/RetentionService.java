package io.agentflow.api.service;

import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.dto.EraseRunDataResponse;
import io.agentflow.api.dto.EraseTenantDataResponse;
import io.agentflow.api.dto.RetentionPurgeResponse;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.CheckpointRepository;
import io.agentflow.api.repository.MessageRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RetentionService {

    private static final String RESUME_META_KEY = "_resume";

    private final RunRepository runs;
    private final MessageRepository messages;
    private final CheckpointRepository checkpoints;
    private final StringRedisTemplate redis;
    private final AgentflowProperties props;

    public RetentionService(
            RunRepository runs,
            MessageRepository messages,
            CheckpointRepository checkpoints,
            StringRedisTemplate redis,
            AgentflowProperties props) {
        this.runs = runs;
        this.messages = messages;
        this.checkpoints = checkpoints;
        this.redis = redis;
        this.props = props;
    }

    @Transactional
    public EraseRunDataResponse eraseRunData(String runId) {
        AccessControl.require(Role.ADMIN);
        String tenantId = AccessControl.tenantId(Role.ADMIN);
        RunEntity run = runs.findByIdAndTenantId(runId, tenantId)
                .orElseThrow(() -> new RunNotFoundException(runId));

        if (run.getStatus() == RunStatus.PENDING || run.getStatus() == RunStatus.RUNNING) {
            throw new RunConflictException(
                    "Cannot erase run " + runId + " memory while status is " + run.getStatus());
        }

        long msgDeleted = messages.deleteByRunId(runId);
        long cpDeleted = checkpoints.deleteByRunId(runId);
        clearTranscriptFields(run);
        runs.save(run);
        deleteEventLog(runId);

        return new EraseRunDataResponse(runId, msgDeleted, cpDeleted);
    }

    @Transactional
    public EraseTenantDataResponse eraseTenantData() {
        AccessControl.require(Role.ADMIN);
        String tenantId = AccessControl.tenantId(Role.ADMIN);
        List<RunEntity> tenantRuns = runs.findAllByTenantId(tenantId);

        long totalMessages = 0;
        long totalCheckpoints = 0;
        for (RunEntity run : tenantRuns) {
            totalMessages += messages.deleteByRunId(run.getId());
            totalCheckpoints += checkpoints.deleteByRunId(run.getId());
            clearTranscriptFields(run);
            deleteEventLog(run.getId());
        }
        runs.saveAll(tenantRuns);

        return new EraseTenantDataResponse(
                tenantId, tenantRuns.size(), totalMessages, totalCheckpoints);
    }

    @Transactional
    public RetentionPurgeResponse purgeExpired(String tenantId, boolean dryRun) {
        AccessControl.require(Role.ADMIN);
        String scopedTenant = AccessControl.tenantId(Role.ADMIN);
        if (tenantId != null && !tenantId.equals(scopedTenant)) {
            throw new RunNotFoundException("tenant");
        }
        tenantId = scopedTenant;

        int ttlDays = props.getRetention().getTenantTtlDays();
        if (ttlDays <= 0) {
            return new RetentionPurgeResponse(tenantId, 0, 0, 0);
        }

        Instant cutoff = Instant.now().minus(ttlDays, ChronoUnit.DAYS);
        List<RunEntity> candidates = runs.findRecentByTenantId(
                        tenantId, PageRequest.of(0, props.getRetention().getPurgeBatchSize()))
                .stream()
                .filter(run -> run.getCreatedAt().isBefore(cutoff))
                .filter(run -> isTerminal(run.getStatus()))
                .toList();

        long totalMessages = 0;
        long totalCheckpoints = 0;
        if (!dryRun) {
            for (RunEntity run : candidates) {
                totalMessages += messages.deleteByRunId(run.getId());
                totalCheckpoints += checkpoints.deleteByRunId(run.getId());
                clearTranscriptFields(run);
                deleteEventLog(run.getId());
            }
            runs.saveAll(candidates);
        } else {
            for (RunEntity run : candidates) {
                totalMessages += messages.findAllByRunIdOrderByIndexAsc(run.getId()).size();
                totalCheckpoints += checkpoints.findAllByRunIdOrderByIndexAsc(run.getId()).size();
            }
        }

        return new RetentionPurgeResponse(
                tenantId, candidates.size(), totalMessages, totalCheckpoints);
    }

    private void clearTranscriptFields(RunEntity run) {
        run.setOutput(null);
        Map<String, Object> metadata = new HashMap<>(run.getMetadata());
        metadata.remove(RESUME_META_KEY);
        run.setMetadata(metadata);
    }

    private void deleteEventLog(String runId) {
        String streamKey = props.getEvents().getChannelPrefix()
                + runId
                + props.getEvents().getStreamSuffix();
        redis.delete(streamKey);
    }

    private static boolean isTerminal(RunStatus status) {
        return status == RunStatus.SUCCEEDED
                || status == RunStatus.FAILED
                || status == RunStatus.CANCELLED;
    }
}
