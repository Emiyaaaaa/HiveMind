package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.RunResumeRequest;
import io.agentflow.api.entity.CheckpointEntity;
import io.agentflow.api.entity.RunAuditEventEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.jobs.CancelSignal;
import io.agentflow.api.jobs.JobProducer;
import io.agentflow.api.repository.CheckpointRepository;
import io.agentflow.api.repository.MessageRepository;
import io.agentflow.api.repository.RunAuditEventRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.repository.StepRepository;
import io.agentflow.api.repository.ThreadRepository;
import io.agentflow.api.repository.ToolCallRepository;
import io.agentflow.api.security.AuthPrincipal;
import io.agentflow.api.security.Role;
import io.agentflow.api.security.TenantContext;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class RunAuditServiceTest {

    @BeforeEach
    void setPrincipal() {
        TenantContext.set(new AuthPrincipal("tenant-a", Role.OPERATOR, "ops-user"));
    }

    @AfterEach
    void clearPrincipal() {
        TenantContext.clear();
    }

    @Test
    void cancelRecordsAuditEvent() {
        RunRepository runs = mock(RunRepository.class);
        RunAuditEventRepository auditEvents = mock(RunAuditEventRepository.class);
        CancelSignal cancelSignal = mock(CancelSignal.class);
        RunEntity run = new RunEntity();
        run.setId("run-1");
        run.setTenantId("tenant-a");
        run.setAgentId("agent-1");
        run.setAdapter("echo");
        run.setStatus(RunStatus.RUNNING);
        when(runs.findByIdAndTenantId("run-1", "tenant-a")).thenReturn(Optional.of(run));

        RunService service = service(runs, auditEvents, cancelSignal);
        service.cancel("run-1");

        ArgumentCaptor<RunAuditEventEntity> captor =
                ArgumentCaptor.forClass(RunAuditEventEntity.class);
        verify(auditEvents).save(captor.capture());
        RunAuditEventEntity event = captor.getValue();
        assertThat(event.getRunId()).isEqualTo("run-1");
        assertThat(event.getAction()).isEqualTo("cancel");
        assertThat(event.getActorSubject()).isEqualTo("ops-user");
        assertThat(event.getActorRole()).isEqualTo("operator");
        verify(cancelSignal).requestCancel("run-1");
    }

    @Test
    void resumeRecordsAuditEventWithDetail() {
        RunRepository runs = mock(RunRepository.class);
        RunAuditEventRepository auditEvents = mock(RunAuditEventRepository.class);
        CheckpointRepository checkpoints = mock(CheckpointRepository.class);
        RunEntity run = new RunEntity();
        run.setId("run-2");
        run.setTenantId("tenant-a");
        run.setAgentId("agent-1");
        run.setAdapter("echo");
        run.setStatus(RunStatus.WAITING_HUMAN);
        run.setInput(Map.of("prompt", "hold"));
        run.setMetadata(Map.of());
        when(runs.findByIdAndTenantId("run-2", "tenant-a")).thenReturn(Optional.of(run));
        when(runs.save(any())).thenAnswer(call -> call.getArgument(0));
        CheckpointEntity cp = new CheckpointEntity();
        cp.setIndex(3);
        when(checkpoints.findAllByRunIdOrderByIndexAsc("run-2")).thenReturn(List.of(cp));

        RunService service = service(runs, auditEvents, mock(CancelSignal.class), checkpoints);
        RunResumeRequest req = new RunResumeRequest();
        req.setInput(Map.of("approval", "ok"));
        service.resume("run-2", req);

        ArgumentCaptor<RunAuditEventEntity> captor =
                ArgumentCaptor.forClass(RunAuditEventEntity.class);
        verify(auditEvents).save(captor.capture());
        RunAuditEventEntity event = captor.getValue();
        assertThat(event.getAction()).isEqualTo("resume");
        assertThat(event.getActorSubject()).isEqualTo("ops-user");
        assertThat(event.getDetail()).containsEntry("checkpoint_index", 3);
        assertThat(event.getDetail()).containsEntry("input", Map.of("approval", "ok"));
    }

    @Test
    void listAuditReturnsTenantScopedEvents() {
        RunRepository runs = mock(RunRepository.class);
        RunAuditEventRepository auditEvents = mock(RunAuditEventRepository.class);
        RunEntity run = new RunEntity();
        run.setId("run-3");
        run.setTenantId("tenant-a");
        run.setAgentId("agent-1");
        run.setAdapter("echo");
        when(runs.findByIdAndTenantId("run-3", "tenant-a")).thenReturn(Optional.of(run));
        RunAuditEventEntity stored = new RunAuditEventEntity();
        stored.setId("aud-1");
        stored.setTenantId("tenant-a");
        stored.setRunId("run-3");
        stored.setAction("cancel");
        stored.setActorSubject("ops-user");
        stored.setActorRole("operator");
        when(auditEvents.findAllByRunIdAndTenantIdOrderByCreatedAtAscIdAsc(
                        eq("run-3"), eq("tenant-a")))
                .thenReturn(List.of(stored));

        TenantContext.set(new AuthPrincipal("tenant-a", Role.VIEWER, "viewer-1"));
        RunService service = service(runs, auditEvents, mock(CancelSignal.class));
        assertThat(service.listAudit("run-3")).hasSize(1);
        assertThat(service.listAudit("run-3").getFirst().getAction()).isEqualTo("cancel");
    }

    private static RunService service(
            RunRepository runs, RunAuditEventRepository auditEvents, CancelSignal cancelSignal) {
        return service(runs, auditEvents, cancelSignal, mock(CheckpointRepository.class));
    }

    private static RunService service(
            RunRepository runs,
            RunAuditEventRepository auditEvents,
            CancelSignal cancelSignal,
            CheckpointRepository checkpoints) {
        return new RunService(
                runs,
                mock(StepRepository.class),
                mock(MessageRepository.class),
                mock(ToolCallRepository.class),
                checkpoints,
                auditEvents,
                mock(AgentService.class),
                mock(ThreadRepository.class),
                mock(JobProducer.class),
                cancelSignal,
                mock(AttachmentService.class));
    }
}
