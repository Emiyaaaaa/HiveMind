package io.agentflow.api.security;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.config.JacksonConfig;
import io.agentflow.api.config.PropertiesConfig;
import io.agentflow.api.controller.AgentsController;
import io.agentflow.api.controller.GlobalExceptionHandler;
import io.agentflow.api.controller.HealthController;
import io.agentflow.api.dto.AgentResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.service.AgentService;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(controllers = {AgentsController.class, HealthController.class})
@Import({
    JacksonConfig.class,
    PropertiesConfig.class,
    AgentflowProperties.class,
    AuthFilter.class,
    GlobalExceptionHandler.class
})
@TestPropertySource(
        properties = {
            "agentflow.version=0.1.0",
            "agentflow.adapters=echo",
            "agentflow.auth.enabled=true",
            "agentflow.auth.keys[0].key=admin-a",
            "agentflow.auth.keys[0].tenant-id=tenant-a",
            "agentflow.auth.keys[0].role=admin",
            "agentflow.auth.keys[1].key=viewer-a",
            "agentflow.auth.keys[1].tenant-id=tenant-a",
            "agentflow.auth.keys[1].role=viewer",
        })
class AuthTenantWebTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    AgentService agentService;

    @Test
    void healthRemainsOpen() throws Exception {
        mvc.perform(get("/v1/health")).andExpect(status().isOk());
    }

    @Test
    void missingKeyIsUnauthorized() throws Exception {
        mvc.perform(get("/v1/agents")).andExpect(status().isUnauthorized());
    }

    @Test
    void adminCanCreateAgent() throws Exception {
        AgentResponse dto = newAgent("id1", "tenant-a", "writer");
        Mockito.when(agentService.create(Mockito.any())).thenReturn(dto);

        mvc.perform(
                        post("/v1/agents")
                                .header("X-Api-Key", "admin-a")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"name\":\"writer\",\"adapter\":\"echo\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.tenant_id").value("tenant-a"))
                .andExpect(jsonPath("$.name").value("writer"));
    }

    @Test
    void invalidKeyIsUnauthorized() throws Exception {
        mvc.perform(get("/v1/agents").header("Authorization", "Bearer nope"))
                .andExpect(status().isUnauthorized());
    }

    private static AgentResponse newAgent(String id, String tenantId, String name) {
        AgentEntity entity = new AgentEntity();
        entity.setId(id);
        entity.setTenantId(tenantId);
        entity.setName(name);
        entity.setAdapter("echo");
        entity.setConfig(Map.of());
        entity.setVersion(1);
        entity.setCreatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        entity.setUpdatedAt(Instant.parse("2026-01-01T00:00:00Z"));
        return AgentResponse.fromEntity(entity);
    }
}
