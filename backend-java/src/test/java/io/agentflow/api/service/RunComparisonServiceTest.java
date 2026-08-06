package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.RunComparisonPreviewRequest;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunStatus;
import io.agentflow.api.repository.RunRepository;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class RunComparisonServiceTest {

    @Test
    void comparesSimpleRunSummary() {
        RunRepository runs = mock(RunRepository.class);
        RunEntity baseline = run("baseline", 1, Map.of("answer", "old"));
        RunEntity candidate = run("candidate", 2, Map.of("answer", "new"));
        when(runs.findById("baseline")).thenReturn(Optional.of(baseline));
        when(runs.findById("candidate")).thenReturn(Optional.of(candidate));

        var result = new RunComparisonService(runs)
                .preview(new RunComparisonPreviewRequest("baseline", "candidate"));

        assertThat(result.baseline().agentVersion()).isEqualTo(1);
        assertThat(result.candidate().agentVersion()).isEqualTo(2);
        assertThat(result.agentVersionChanged()).isTrue();
        assertThat(result.inputChanged()).isFalse();
        assertThat(result.outputChanged()).isTrue();
        assertThat(result.statusChanged()).isFalse();
        assertThat(result.errorChanged()).isFalse();
    }

    private static RunEntity run(String id, int version, Map<String, Object> output) {
        RunEntity run = new RunEntity();
        run.setId(id);
        run.setAgentId("agent-1");
        run.setStatus(RunStatus.SUCCEEDED);
        run.setInput(Map.of("prompt", "same"));
        run.setOutput(output);
        run.setMetadata(Map.of("_agentflow", Map.of("agent_version", version)));
        return run;
    }
}
