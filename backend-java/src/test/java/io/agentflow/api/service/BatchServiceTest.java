package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.BatchCreateRequest;
import io.agentflow.api.dto.BatchCreateRequest.BatchItemRequest;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.RunBatchEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.RunBatchRepository;
import io.agentflow.api.repository.RunRepository;
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

class BatchServiceTest {

    @BeforeEach
    void setPrincipal() {
        TenantContext.set(new AuthPrincipal("default", Role.ADMIN, "test"));
    }

    @AfterEach
    void clearPrincipal() {
        TenantContext.clear();
    }

    @Test
    void createsRunsAndPersistsBatchManifest() {
        RunBatchRepository batches = mock(RunBatchRepository.class);
        RunRepository runs = mock(RunRepository.class);
        AgentService agents = mock(AgentService.class);
        RunService runService = mock(RunService.class);
        BatchService service = new BatchService(batches, runs, agents, runService);

        AgentEntity agent = new AgentEntity();
        agent.setId("agent-1");
        agent.setTenantId("default");
        agent.setAdapter("echo");
        agent.setVersion(3);
        when(agents.getEntity("agent-1")).thenReturn(agent);

        when(batches.save(any())).thenAnswer(invocation -> {
            RunBatchEntity entity = invocation.getArgument(0);
            if (entity.getId() == null) {
                entity.setId("batch-1");
            }
            return entity;
        });

        RunEntity run1 = run("run-1");
        RunEntity run2 = run("run-2");
        when(runService.createTaggedRun(eq(agent), eq(null), any(), any()))
                .thenReturn(run1, run2);
        when(runs.findByIdAndTenantId("run-1", "default")).thenReturn(Optional.of(run1));
        when(runs.findByIdAndTenantId("run-2", "default")).thenReturn(Optional.of(run2));

        BatchCreateRequest request = new BatchCreateRequest();
        request.setAgentId("agent-1");
        BatchItemRequest a = new BatchItemRequest();
        a.setInput(Map.of("prompt", "a"));
        BatchItemRequest b = new BatchItemRequest();
        b.setInput(Map.of("prompt", "b"));
        request.setItems(List.of(a, b));

        var response = service.create(request);

        assertThat(response.runIds()).containsExactly("run-1", "run-2");
        assertThat(response.total()).isEqualTo(2);
        assertThat(response.status()).isEqualTo("pending");

        ArgumentCaptor<RunBatchEntity> captor = ArgumentCaptor.forClass(RunBatchEntity.class);
        verify(batches, org.mockito.Mockito.atLeastOnce()).save(captor.capture());
        assertThat(captor.getValue().getRunIds()).containsExactly("run-1", "run-2");
    }

    @Test
    void rejectsEmptyItems() {
        BatchService service = new BatchService(
                mock(RunBatchRepository.class),
                mock(RunRepository.class),
                mock(AgentService.class),
                mock(RunService.class));
        BatchCreateRequest request = new BatchCreateRequest();
        request.setAgentId("agent-1");
        request.setItems(List.of());
        assertThatThrownBy(() -> service.create(request)).isInstanceOf(BatchException.class);
    }

    private static RunEntity run(String id) {
        RunEntity entity = new RunEntity();
        entity.setId(id);
        entity.setAgentId("agent-1");
        entity.setTenantId("default");
        entity.setAdapter("echo");
        entity.setStatus(RunStatus.PENDING);
        entity.setInput(Map.of());
        entity.setMetadata(Map.of());
        return entity;
    }
}
