package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.AgentQuotaStatusResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.AgentQuotaUsageEntity;
import io.agentflow.api.repository.AgentQuotaUsageRepository;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class AgentQuotaServiceTest {

    @Test
    void inactiveWhenNoQuotaConfig() {
        AgentQuotaUsageRepository repo = mock(AgentQuotaUsageRepository.class);
        AgentQuotaService service = new AgentQuotaService(repo);
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setConfig(Map.of());

        AgentQuotaStatusResponse status = service.status(agent);

        assertThat(status.isActive()).isFalse();
        assertThat(status.isExceeded()).isFalse();
    }

    @Test
    void assertCanCreateRunBlocksWhenTokensExhausted() {
        AgentQuotaUsageRepository repo = mock(AgentQuotaUsageRepository.class);
        AgentQuotaService service = new AgentQuotaService(repo);
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setConfig(Map.of(
                "quota",
                Map.of("period", "day", "max_tokens", 10, "enforce", true)));

        String key = AgentQuotaService.periodKey("day", Instant.now());
        AgentQuotaUsageEntity row = new AgentQuotaUsageEntity();
        row.setTokensIn(6);
        row.setTokensOut(4);
        row.setCostUsd(0.01);
        when(repo.findByAgentIdAndPeriodKeyForUpdate("a1", key)).thenReturn(Optional.of(row));

        assertThatThrownBy(() -> service.assertCanCreateRun(agent))
                .isInstanceOf(AgentQuotaExceededException.class)
                .hasMessageContaining("tokens=10/10");
    }

    @Test
    void enforceFalseNeverBlocks() {
        AgentQuotaUsageRepository repo = mock(AgentQuotaUsageRepository.class);
        AgentQuotaService service = new AgentQuotaService(repo);
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setConfig(Map.of(
                "quota", Map.of("max_tokens", 1, "enforce", false)));

        service.assertCanCreateRun(agent);
    }
}
