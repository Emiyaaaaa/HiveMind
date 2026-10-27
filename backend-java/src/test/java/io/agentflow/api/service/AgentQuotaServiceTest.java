package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.agentflow.api.dto.AgentQuotaStatusResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.AgentQuotaUsageEntity;
import io.agentflow.api.entity.ProjectEntity;
import io.agentflow.api.entity.ProjectQuotaConfigEntity;
import io.agentflow.api.entity.ProjectQuotaUsageEntity;
import io.agentflow.api.entity.TenantQuotaConfigEntity;
import io.agentflow.api.entity.TenantQuotaUsageEntity;
import io.agentflow.api.repository.AgentQuotaUsageRepository;
import io.agentflow.api.repository.ProjectQuotaConfigRepository;
import io.agentflow.api.repository.ProjectQuotaUsageRepository;
import io.agentflow.api.repository.ProjectRepository;
import io.agentflow.api.repository.TenantQuotaConfigRepository;
import io.agentflow.api.repository.TenantQuotaUsageRepository;
import io.agentflow.api.security.AuthPrincipal;
import io.agentflow.api.security.Role;
import io.agentflow.api.security.TenantContext;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

class AgentQuotaServiceTest {

    @AfterEach
    void clearPrincipal() {
        TenantContext.clear();
    }

    @Test
    void inactiveWhenNoQuotaConfig() {
        AgentQuotaService service = service();
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setTenantId("default");
        agent.setConfig(Map.of());

        AgentQuotaStatusResponse status = service.status(agent);

        assertThat(status.isActive()).isFalse();
        assertThat(status.isExceeded()).isFalse();
        assertThat(status.getScope()).isEqualTo("agent");
        assertThat(status.getScopeId()).isEqualTo("a1");
    }

    @Test
    void assertCanCreateRunBlocksWhenTokensExhausted() {
        Fixtures fixtures = fixtures();
        AgentQuotaService service = fixtures.service();
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
        when(fixtures.agentUsage.findByAgentIdAndPeriodKeyForUpdate("a1", key))
                .thenReturn(Optional.of(row));

        assertThatThrownBy(() -> service.assertCanCreateRun(agent))
                .isInstanceOf(AgentQuotaExceededException.class)
                .hasMessageContaining("Agent quota exceeded")
                .hasMessageContaining("tokens=10/10");
    }

    @Test
    void enforceFalseNeverBlocks() {
        AgentQuotaService service = service();
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setConfig(Map.of(
                "quota", Map.of("max_tokens", 1, "enforce", false)));

        service.assertCanCreateRun(agent);
    }

    @Test
    void projectQuotaBlocksBeforeAgentQuota() {
        Fixtures fixtures = fixtures();
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setTenantId("default");
        agent.setProjectId("p1");
        agent.setConfig(Map.of("quota", Map.of("max_tokens", 100, "enforce", true)));

        ProjectQuotaConfigEntity config = new ProjectQuotaConfigEntity();
        config.setPeriod("day");
        config.setMaxTokens(3);
        config.setEnforce(true);
        when(fixtures.projectConfigs.findByProjectId("p1")).thenReturn(Optional.of(config));

        String key = AgentQuotaService.periodKey("day", Instant.now());
        ProjectQuotaUsageEntity usage = new ProjectQuotaUsageEntity();
        usage.setTokensIn(2);
        usage.setTokensOut(1);
        when(fixtures.projectUsage.findByProjectIdAndPeriodKeyForUpdate("p1", key))
                .thenReturn(Optional.of(usage));

        assertThatThrownBy(() -> fixtures.service().assertCanCreateRun(agent))
                .isInstanceOf(AgentQuotaExceededException.class)
                .hasMessageContaining("Project quota exceeded")
                .hasMessageContaining("tokens=3/3");
    }

    @Test
    void tenantQuotaBlocksWhenProjectHasRoom() {
        Fixtures fixtures = fixtures();
        AgentEntity agent = new AgentEntity();
        agent.setId("a1");
        agent.setTenantId("org-1");
        agent.setProjectId("p1");
        agent.setConfig(Map.of());

        TenantQuotaConfigEntity config = new TenantQuotaConfigEntity();
        config.setPeriod("month");
        config.setMaxCostUsd(1.0);
        config.setEnforce(true);
        when(fixtures.tenantConfigs.findByTenantId("org-1")).thenReturn(Optional.of(config));

        String key = AgentQuotaService.periodKey("month", Instant.now());
        TenantQuotaUsageEntity usage = new TenantQuotaUsageEntity();
        usage.setCostUsd(1.25);
        when(fixtures.tenantUsage.findByTenantIdAndPeriodKeyForUpdate("org-1", key))
                .thenReturn(Optional.of(usage));

        Throwable thrown =
                org.assertj.core.api.Assertions.catchThrowable(
                        () -> fixtures.service().assertCanCreateRun(agent));
        assertThat(thrown).isInstanceOf(AgentQuotaExceededException.class);
        AgentQuotaExceededException ex = (AgentQuotaExceededException) thrown;
        assertThat(ex.getScope()).isEqualTo("tenant");
        assertThat(ex.getScopeId()).isEqualTo("org-1");
        assertThat(ex.getAgentId()).isEqualTo("a1");
        assertThat(ex.getMessage()).contains("Tenant quota exceeded");
    }

    @Test
    void projectStatusReportsUsage() {
        TenantContext.set(new AuthPrincipal("default", Role.VIEWER, "viewer"));
        Fixtures fixtures = fixtures();
        ProjectEntity project = new ProjectEntity();
        project.setId("p1");
        project.setTenantId("default");
        when(fixtures.projects.findByIdAndTenantId("p1", "default")).thenReturn(Optional.of(project));

        ProjectQuotaConfigEntity config = new ProjectQuotaConfigEntity();
        config.setPeriod("month");
        config.setMaxTokens(10);
        config.setEnforce(true);
        when(fixtures.projectConfigs.findByProjectId("p1")).thenReturn(Optional.of(config));

        String key = AgentQuotaService.periodKey("month", Instant.now());
        ProjectQuotaUsageEntity usage = new ProjectQuotaUsageEntity();
        usage.setTokensIn(4);
        usage.setTokensOut(1);
        usage.setRunCount(2);
        when(fixtures.projectUsage.findByProjectIdAndPeriodKey("p1", key))
                .thenReturn(Optional.of(usage));

        AgentQuotaStatusResponse status = fixtures.service().projectStatus("p1");

        assertThat(status.getScope()).isEqualTo("project");
        assertThat(status.getProjectId()).isEqualTo("p1");
        assertThat(status.isActive()).isTrue();
        assertThat(status.getUsedTokens()).isEqualTo(5);
        assertThat(status.getRemainingTokens()).isEqualTo(5);
        assertThat(status.getRunCount()).isEqualTo(2);
        assertThat(status.isExceeded()).isFalse();
    }

    private static AgentQuotaService service() {
        return fixtures().service();
    }

    private static Fixtures fixtures() {
        AgentQuotaUsageRepository agentUsage = mock(AgentQuotaUsageRepository.class);
        ProjectQuotaUsageRepository projectUsage = mock(ProjectQuotaUsageRepository.class);
        TenantQuotaUsageRepository tenantUsage = mock(TenantQuotaUsageRepository.class);
        ProjectQuotaConfigRepository projectConfigs = mock(ProjectQuotaConfigRepository.class);
        TenantQuotaConfigRepository tenantConfigs = mock(TenantQuotaConfigRepository.class);
        ProjectRepository projects = mock(ProjectRepository.class);
        lenient().when(agentUsage.findByAgentIdAndPeriodKey(any(), any())).thenReturn(Optional.empty());
        lenient()
                .when(agentUsage.findByAgentIdAndPeriodKeyForUpdate(any(), any()))
                .thenReturn(Optional.empty());
        lenient()
                .when(projectUsage.findByProjectIdAndPeriodKey(any(), any()))
                .thenReturn(Optional.empty());
        lenient()
                .when(projectUsage.findByProjectIdAndPeriodKeyForUpdate(any(), any()))
                .thenReturn(Optional.empty());
        lenient()
                .when(tenantUsage.findByTenantIdAndPeriodKey(any(), any()))
                .thenReturn(Optional.empty());
        lenient()
                .when(tenantUsage.findByTenantIdAndPeriodKeyForUpdate(any(), any()))
                .thenReturn(Optional.empty());
        lenient().when(projectConfigs.findByProjectId(any())).thenReturn(Optional.empty());
        lenient().when(tenantConfigs.findByTenantId(any())).thenReturn(Optional.empty());
        lenient().when(projects.findByIdAndTenantId(any(), any())).thenReturn(Optional.empty());
        return new Fixtures(
                agentUsage, projectUsage, tenantUsage, projectConfigs, tenantConfigs, projects);
    }

    private record Fixtures(
            AgentQuotaUsageRepository agentUsage,
            ProjectQuotaUsageRepository projectUsage,
            TenantQuotaUsageRepository tenantUsage,
            ProjectQuotaConfigRepository projectConfigs,
            TenantQuotaConfigRepository tenantConfigs,
            ProjectRepository projects) {

        AgentQuotaService service() {
            return new AgentQuotaService(
                    agentUsage, projectUsage, tenantUsage, projectConfigs, tenantConfigs, projects);
        }
    }
}
