package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.RegressionExecutionCreateRequest;
import io.agentflow.api.dto.RunComparisonResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.AgentVersionEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.AgentVersionRepository;
import io.agentflow.api.repository.RunRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class RegressionExecutionServiceTest {

    @Test
    void createsPinnedCandidatesAndIgnoresOutputDifferences() {
        RunRepository runs = mock(RunRepository.class);
        AgentVersionRepository versions = mock(AgentVersionRepository.class);
        AgentService agents = mock(AgentService.class);
        RunService runService = mock(RunService.class);
        RegressionExecutionStore store = mock(RegressionExecutionStore.class);
        RunComparisonService comparisons = mock(RunComparisonService.class);
        RegressionExecutionService service = new RegressionExecutionService(
                runs, versions, agents, runService, store, comparisons);
        RunEntity baseline1 = run("base-1", RunStatus.SUCCEEDED, Map.of("prompt", "one"));
        RunEntity candidate1 = run("candidate-1", RunStatus.PENDING, Map.of("prompt", "one"));
        AgentEntity agent = new AgentEntity();
        agent.setId("agent-1");
        agent.setVersion(4);
        AgentVersionEntity snapshot = new AgentVersionEntity();
        snapshot.setAdapter("echo");
        when(runs.findAllById(List.of("base-1"))).thenReturn(List.of(baseline1));
        when(runs.findAllById(List.of("candidate-1"))).thenReturn(List.of(candidate1));
        when(agents.getEntity("agent-1")).thenReturn(agent);
        when(versions.findByAgentIdAndVersion("agent-1", 4)).thenReturn(Optional.of(snapshot));
        when(runService.createPinnedCopies(any(), any(), any(Integer.class), any()))
                .thenReturn(List.of(candidate1));
        var created = service.create(new RegressionExecutionCreateRequest(List.of("base-1")));

        ArgumentCaptor<RegressionExecutionManifest> manifest =
                ArgumentCaptor.forClass(RegressionExecutionManifest.class);
        verify(store).save(manifest.capture());
        verify(runService).createPinnedCopies(
                "agent-1",
                "echo",
                4,
                List.of(Map.of("prompt", "one")));
        verify(runService).enqueueCandidates(List.of(candidate1));
        assertThat(created.status()).isEqualTo("pending");
        assertThat(created.candidateAgentVersion()).isEqualTo(4);
        when(store.find(created.executionId())).thenReturn(Optional.of(manifest.getValue()));

        candidate1.setStatus(RunStatus.SUCCEEDED);
        RunComparisonResponse comparison = mock(RunComparisonResponse.class);
        when(comparison.outputChanged()).thenReturn(true);
        when(comparisons.preview(any())).thenReturn(comparison);
        var results = service.results(created.executionId());

        assertThat(results.passedCases()).isEqualTo(1);
        assertThat(results.failedCases()).isZero();
    }

    private static RunEntity run(String id, RunStatus status, Map<String, Object> input) {
        RunEntity run = new RunEntity();
        run.setId(id);
        run.setAgentId("agent-1");
        run.setAdapter("echo");
        run.setStatus(status);
        run.setInput(input);
        return run;
    }

}
