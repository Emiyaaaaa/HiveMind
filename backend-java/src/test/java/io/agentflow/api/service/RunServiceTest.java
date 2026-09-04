package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.RunCreateRequest;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.jobs.CancelSignal;
import io.agentflow.api.jobs.JobProducer;
import io.agentflow.api.jobs.TemporalWorkflowClient;
import io.agentflow.api.repository.CheckpointRepository;
import io.agentflow.api.repository.MessageRepository;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.repository.StepRepository;
import io.agentflow.api.repository.ThreadRepository;
import io.agentflow.api.repository.ToolCallRepository;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class RunServiceTest {

    @Test
    void createPinsVersionAndReplacesClientInternalMetadata() {
        RunRepository runs = mock(RunRepository.class);
        AgentService agents = mock(AgentService.class);
        AgentEntity agent = new AgentEntity();
        agent.setId("agent-1");
        agent.setAdapter("echo");
        agent.setVersion(3);
        when(agents.getEntity("agent-1")).thenReturn(agent);
        when(runs.save(any())).thenAnswer(call -> {
            RunEntity run = call.getArgument(0);
            run.setId("run-1");
            return run;
        });
        RunService service = service(runs, agents);
        RunCreateRequest request = new RunCreateRequest();
        request.setAgentId("agent-1");
        request.setMetadata(Map.of(
                "trace_id", "kept",
                "_agentflow", Map.of("agent_version", 999, "injected", true)));

        service.create(request);

        verify(runs).save(argThat(run -> run.getMetadata().equals(Map.of(
                "trace_id", "kept",
                "_agentflow", Map.of("agent_version", 3)))));
    }

    @Test
    void createPinnedCopiesUsesSpecifiedSnapshotVersion() {
        RunRepository runs = mock(RunRepository.class);
        when(runs.saveAll(any())).thenAnswer(call -> {
            List<RunEntity> saved = call.getArgument(0);
            saved.getFirst().setId("candidate-1");
            return saved;
        });
        RunService service = service(runs, mock(AgentService.class));

        List<RunEntity> candidates = service.createPinnedCopies(
                "agent-1", "echo", 4, List.of(Map.of("prompt", "hello")));

        assertThat(candidates.getFirst().getInput()).isEqualTo(Map.of("prompt", "hello"));
        assertThat(candidates.getFirst().getMetadata())
                .isEqualTo(Map.of("_agentflow", Map.of("agent_version", 4)));
    }

    private static RunService service(RunRepository runs, AgentService agents) {
        return new RunService(
                runs,
                mock(StepRepository.class),
                mock(MessageRepository.class),
                mock(ToolCallRepository.class),
                mock(CheckpointRepository.class),
                agents,
                mock(ThreadRepository.class),
                mock(JobProducer.class),
                mock(CancelSignal.class));
    }
}
